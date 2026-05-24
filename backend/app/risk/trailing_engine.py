"""Trade management after entry."""

from __future__ import annotations

from backend.app.config.models import RiskConfig
from backend.app.core.models import ManagementAction, ManagementDecision, OpenPosition, Side
from backend.app.data.models import Candle


class TrailingEngine:
    """Manage partials, breakeven, and structural trailing.

    The engine is intentionally conservative when candle OHLC data creates path
    ambiguity. If a candle could have both hit the stop and reached a target,
    the stop is assumed to have happened first.
    """

    def __init__(self, risk_config: RiskConfig) -> None:
        self.risk_config = risk_config

    def evaluate(self, position: OpenPosition, candles: tuple[Candle, ...]) -> tuple[ManagementDecision, ...]:
        if not candles:
            return ()

        latest = candles[-1]
        position.bars_held += 1
        current_r = position.current_r_multiple(latest.close)
        position.best_r_multiple = max(position.best_r_multiple, current_r)
        position.worst_r_multiple = min(position.worst_r_multiple, current_r)
        decisions: list[ManagementDecision] = []

        if self._stop_breached(position, latest):
            return (
                ManagementDecision(
                    action=ManagementAction.EXIT,
                    reason="structural stop breached",
                    price=position.stop_price,
                ),
            )

        if not position.first_partial_taken and self._first_target_reached(position, latest):
            position.first_target_hit_after_bars = position.bars_held
            if (
                position.best_r_multiple >= self.risk_config.management.impulsive_move_threshold_r
                or position.bars_held <= max(1, self.risk_config.management.early_exit_after_bars - 1)
            ):
                position.follow_through_state = "impulsive"
            else:
                position.follow_through_state = "balanced"
            partial_quantity = position.initial_quantity * position.risk_plan.first_partial_fraction
            decisions.append(
                ManagementDecision(
                    action=ManagementAction.TAKE_PARTIAL,
                    reason="first partial reached at +1R",
                    price=position.risk_plan.first_partial_at_price,
                    quantity=partial_quantity,
                )
            )
            if position.risk_plan.breakeven_after_partial:
                decisions.append(
                    ManagementDecision(
                        action=ManagementAction.MOVE_STOP,
                        reason="move stop to breakeven after first partial",
                        price=position.entry_price,
                    )
                )
            return tuple(decisions)

        if not position.first_partial_taken and self._should_exit_early(position, latest):
            return (
                ManagementDecision(
                    action=ManagementAction.EXIT,
                    reason="early failure exit due to missing follow-through",
                    price=latest.close,
                ),
            )

        if position.first_partial_taken:
            candidate = self._structural_trailing_stop(position, candles)
            if candidate is not None:
                decisions.append(
                    ManagementDecision(
                        action=ManagementAction.MOVE_STOP,
                        reason="trail stop with recent candle structure",
                        price=candidate,
                    )
                )
        return tuple(decisions)

    def _stop_breached(self, position: OpenPosition, candle: Candle) -> bool:
        if position.side is Side.LONG:
            return candle.low <= position.stop_price
        return candle.high >= position.stop_price

    def _first_target_reached(self, position: OpenPosition, candle: Candle) -> bool:
        if position.side is Side.LONG:
            return candle.high >= position.risk_plan.first_partial_at_price
        return candle.low <= position.risk_plan.first_partial_at_price

    def _structural_trailing_stop(
        self,
        position: OpenPosition,
        candles: tuple[Candle, ...],
    ) -> float | None:
        lookback = self.risk_config.management.trailing_lookback_bars
        if position.follow_through_state == "impulsive":
            lookback = max(lookback, self.risk_config.management.impulsive_trailing_lookback_bars)
        if len(candles) <= lookback:
            return None
        reference = candles[-1 - lookback]
        if position.side is Side.LONG:
            candidate = reference.low
            if candidate > position.stop_price and candidate < candles[-1].close:
                return candidate
            return None
        candidate = reference.high
        if candidate < position.stop_price and candidate > candles[-1].close:
            return candidate
        return None

    def _should_exit_early(self, position: OpenPosition, latest: Candle) -> bool:
        if position.bars_held < self.risk_config.management.early_exit_after_bars:
            return False
        if position.best_r_multiple >= self.risk_config.management.early_exit_min_progress_r:
            return False
        current_r = position.current_r_multiple(latest.close)
        return current_r <= self.risk_config.management.early_exit_max_adverse_close_r
