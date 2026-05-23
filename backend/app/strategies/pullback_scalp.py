"""Momentum -> pullback -> re-expansion strategy."""

from __future__ import annotations

from statistics import fmean

from backend.app.config.models import (
    StrategyRuleConfig,
    StrategyTriggerConfig,
    TimeframeProfileConfig,
)
from backend.app.core.models import MarketSnapshot, ScannerDecision, Side, TradeSignal
from backend.app.scanner.filters import close_position_for_side, safe_ratio

from .base import BaseStrategy


class PullbackScalpStrategy(BaseStrategy):
    """Convert a valid scanner narrative into an executable signal."""

    def __init__(
        self,
        strategy_config: StrategyRuleConfig,
        trigger_config: StrategyTriggerConfig,
        execution_timeframe: str,
        profile: TimeframeProfileConfig | None = None,
    ) -> None:
        self.strategy_config = strategy_config
        self.trigger_config = trigger_config
        self.execution_timeframe = execution_timeframe
        self.profile = profile

    def evaluate(self, snapshot: MarketSnapshot, scanner_decision: ScannerDecision) -> TradeSignal | None:
        if not scanner_decision.is_tradeable:
            return None

        current = snapshot.latest(self.execution_timeframe)
        if current is None or scanner_decision.side is None:
            return None

        side = scanner_decision.side
        if side is Side.LONG and not self.strategy_config.allow_long:
            return None
        if side is Side.SHORT and not self.strategy_config.allow_short:
            return None

        reference = snapshot.series(self.execution_timeframe)[-6:-1]
        reference_mean_body = fmean(candle.body_size for candle in reference) if reference else 0.0
        trigger_body_ratio = safe_ratio(current.body_size, reference_mean_body, default=0.0)
        trigger_close_position = close_position_for_side(current, side)

        if side is Side.LONG:
            breakout_happened = current.high > float(scanner_decision.trigger_level)
            breakout_confirmed = current.close > float(scanner_decision.trigger_level)
            directional_candle = current.is_bullish
            stop_buffer = current.range_size * self.trigger_config.stop_buffer_ratio
            stop_price = float(scanner_decision.invalidation_level) - stop_buffer
            entry_price = current.close
        else:
            breakout_happened = current.low < float(scanner_decision.trigger_level)
            breakout_confirmed = current.close < float(scanner_decision.trigger_level)
            directional_candle = not current.is_bullish
            stop_buffer = current.range_size * self.trigger_config.stop_buffer_ratio
            stop_price = float(scanner_decision.invalidation_level) + stop_buffer
            entry_price = current.close

        reasons: list[str] = []
        if not breakout_happened:
            return None
        reasons.append("trigger candle breached the pullback structure")

        if self.trigger_config.require_breakout_close and not breakout_confirmed:
            return None
        if self.trigger_config.require_breakout_close:
            reasons.append("trigger candle closed beyond the breakout level")

        if not directional_candle:
            return None
        reasons.append("trigger candle closed in the direction of the trade")

        if trigger_body_ratio < self.trigger_config.min_body_ratio:
            return None
        reasons.append("trigger candle body expansion confirms resumed imbalance")

        if trigger_close_position < self.trigger_config.min_close_position:
            return None
        reasons.append("trigger candle close is near the directional extreme")

        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit <= 0:
            return None
        first_target_price = entry_price + (risk_per_unit * side.multiplier)
        confidence = min(
            1.0,
            (
                min(2.0, scanner_decision.momentum_score) / 2
                + scanner_decision.pullback_score
                + min(2.0, trigger_body_ratio) / 2
                + trigger_close_position
            )
            / 4,
        )

        return TradeSignal(
            strategy_name=self.strategy_config.name,
            symbol=snapshot.symbol,
            timeframe=self.execution_timeframe,
            side=side,
            generated_at=current.close_time,
            entry_price=entry_price,
            stop_price=stop_price,
            first_target_price=first_target_price,
            confidence=confidence,
            reasons=tuple(reasons),
            metadata={
                "profile_name": self.profile.name if self.profile is not None else "default",
                "profile_description": self.profile.description if self.profile is not None else "",
                "profile_runner_emphasis": (
                    self.profile.cadence.runner_emphasis if self.profile is not None else "balanced"
                ),
                "profile_expected_trades_per_day_low": (
                    self.profile.cadence.expected_trades_per_day_low if self.profile is not None else 0
                ),
                "profile_expected_trades_per_day_high": (
                    self.profile.cadence.expected_trades_per_day_high if self.profile is not None else 0
                ),
                "trigger_body_ratio": trigger_body_ratio,
                "trigger_close_position": trigger_close_position,
                "scanner_momentum_score": scanner_decision.momentum_score,
                "scanner_pullback_score": scanner_decision.pullback_score,
            },
        )
