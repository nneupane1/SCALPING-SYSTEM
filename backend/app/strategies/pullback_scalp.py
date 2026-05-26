"""Momentum -> pullback -> re-expansion strategy."""

from __future__ import annotations

from datetime import timedelta
from statistics import fmean

from backend.app.config.models import (
    SessionsConfig,
    StrategyFilterConfig,
    StrategyRuleConfig,
    StrategyTriggerConfig,
    TimeframeProfileConfig,
)
from backend.app.core.models import MarketSnapshot, ScannerDecision, Side, TradeSignal
from backend.app.data.models import Candle
from backend.app.scanner.filters import close_position_for_side, safe_ratio

from .base import BaseStrategy
from .context import assess_context
from .market_state import assess_market_state
from .quality import assess_setup_quality
from .session_context import SessionAssessment, assess_session


class PullbackScalpStrategy(BaseStrategy):
    """Convert a valid scanner narrative into an executable signal."""

    def __init__(
        self,
        strategy_config: StrategyRuleConfig,
        filter_config: StrategyFilterConfig,
        trigger_config: StrategyTriggerConfig,
        execution_timeframe: str,
        profile: TimeframeProfileConfig | None = None,
        sessions_config: SessionsConfig | None = None,
    ) -> None:
        self.strategy_config = strategy_config
        self.filter_config = filter_config
        self.trigger_config = trigger_config
        self.execution_timeframe = execution_timeframe
        configured_trigger_timeframe = trigger_config.timeframe.strip().lower()
        self.trigger_timeframe = (
            execution_timeframe
            if configured_trigger_timeframe in {"", "execution"}
            else trigger_config.timeframe
        )
        self.profile = profile
        self.sessions_config = sessions_config
        self.last_rejection_reason: str | None = None

    def evaluate(self, snapshot: MarketSnapshot, scanner_decision: ScannerDecision) -> TradeSignal | None:
        self.last_rejection_reason = None

        def block(reason: str) -> None:
            self.last_rejection_reason = reason
            return None

        if not scanner_decision.is_tradeable:
            return block("scanner decision is not tradeable")

        execution_candle = snapshot.latest(self.execution_timeframe)
        if execution_candle is None or scanner_decision.side is None:
            return block("missing execution candle or scanner side")

        side = scanner_decision.side
        if side is Side.LONG and not self.strategy_config.allow_long:
            return block("long entries disabled by strategy config")
        if side is Side.SHORT and not self.strategy_config.allow_short:
            return block("short entries disabled by strategy config")

        impulse_range = (
            scanner_decision.impulse_candle.range_size
            if scanner_decision.impulse_candle is not None
            else max(execution_candle.range_size, 1e-12)
        )
        trigger_evaluation = self._find_trigger_candidate(
            snapshot=snapshot,
            scanner_decision=scanner_decision,
            execution_candle=execution_candle,
            side=side,
            impulse_range=impulse_range,
        )
        if trigger_evaluation is None:
            return block(self.last_rejection_reason or "no valid trigger candle found")

        trigger_candle = trigger_evaluation["candle"]
        entry_price = float(trigger_evaluation["entry_price"])
        stop_price = float(trigger_evaluation["stop_price"])
        trigger_body_ratio = float(trigger_evaluation["trigger_body_ratio"])
        trigger_close_position = float(trigger_evaluation["trigger_close_position"])
        breakout_extension_ratio = float(trigger_evaluation["breakout_extension_ratio"])
        pre_breakout_tightness_score = float(trigger_evaluation["pre_breakout_tightness_score"])
        entry_timing_score = float(trigger_evaluation["entry_timing_score"])
        first_target_price = float(trigger_evaluation["first_target_price"])
        effective_max_body_ratio = float(trigger_evaluation["effective_max_body_ratio"])
        reasons = list(trigger_evaluation["reasons"])
        confidence = min(
            1.0,
            (
                scanner_decision.momentum_score
                + scanner_decision.pullback_score
                + entry_timing_score
                + trigger_close_position
            )
            / 4,
        )

        context = assess_context(
            snapshot=snapshot,
            side=side,
            config=self.filter_config.context,
        )
        session = self._assess_session(snapshot)
        if not session.active:
            return block(session.reasons[0] if session.reasons else "session filter blocked entry")
        market_state = assess_market_state(
            snapshot=snapshot,
            side=side,
            config=self.filter_config.market_state,
            execution_timeframe=self.execution_timeframe,
        )
        if market_state.no_trade:
            return block(market_state.reasons[0] if market_state.reasons else "market state no-trade filter blocked entry")
        if context.alignment == "conflicting" and self.filter_config.context.block_on_conflict:
            return block("15m context conflict blocked entry")

        quality = assess_setup_quality(
            scanner_decision=scanner_decision,
            trigger_body_ratio=trigger_body_ratio,
            trigger_close_position=trigger_close_position,
            entry_timing_score=entry_timing_score,
            context=context,
            market_state=market_state,
            session=session,
            config=self.filter_config.quality,
        )
        if self.filter_config.quality.enabled and not quality.accepted:
            return block("setup quality rejected the entry")

        confidence = max(
            0.0,
            min(
                1.0,
                confidence
                + context.confidence_adjustment
                + market_state.confidence_adjustment
                + session.confidence_adjustment,
            ),
        )
        reasons.extend(context.reasons)
        reasons.extend(market_state.reasons)
        reasons.extend(session.reasons)
        reasons.extend(quality.reasons)

        combined_risk_multiplier = (
            context.risk_multiplier
            * market_state.risk_multiplier
            * session.risk_multiplier
            * quality.risk_multiplier
        )

        return TradeSignal(
            strategy_name=self.strategy_config.name,
            symbol=snapshot.symbol,
            timeframe=self.execution_timeframe,
            side=side,
            generated_at=trigger_candle.close_time,
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
                "trigger_timeframe": self.trigger_timeframe,
                "trigger_generated_at": trigger_candle.close_time.isoformat(),
                "context_timeframe": context.timeframe,
                "context_alignment": context.alignment,
                "context_support_score": context.support_score,
                "context_opposing_score": context.opposing_score,
                "market_state": market_state.state,
                "market_state_alignment": market_state.alignment,
                "market_state_efficiency": market_state.efficiency,
                "market_state_overlap_ratio": market_state.overlap_ratio,
                "market_state_alternation_ratio": market_state.alternation_ratio,
                "market_state_compression_ratio": market_state.compression_ratio,
                "session_name": session.session_name,
                "session_phase": session.phase,
                "setup_quality_score": quality.score,
                "setup_quality_label": quality.label,
                "setup_execution_band": quality.execution_band,
                "risk_fraction_multiplier": combined_risk_multiplier,
                "entry_timing_score": entry_timing_score,
                "trigger_body_ratio": trigger_body_ratio,
                "trigger_max_body_ratio": effective_max_body_ratio,
                "trigger_close_position": trigger_close_position,
                "breakout_extension_ratio": breakout_extension_ratio,
                "pre_breakout_tightness_score": pre_breakout_tightness_score,
                "trigger_candle_timeframe": trigger_candle.timeframe,
                "scanner_momentum_score": scanner_decision.momentum_score,
                "scanner_pullback_score": scanner_decision.pullback_score,
                "scanner_impulse_tier": scanner_decision.metrics.get("impulse_tier"),
                "scanner_impulse_quality_score": scanner_decision.metrics.get("impulse_quality_score"),
                "scanner_pullback_quality_label": scanner_decision.metrics.get("pullback_quality_label"),
                "scanner_pullback_overlap_ratio": scanner_decision.metrics.get("pullback_overlap_ratio"),
                "scanner_pullback_tightness_ratio": scanner_decision.metrics.get("pullback_tightness_ratio"),
                "scanner_setup_score": scanner_decision.metrics.get("scanner_setup_score"),
            },
        )

    def _assess_session(self, snapshot: MarketSnapshot) -> SessionAssessment:
        if self.sessions_config is None:
            return SessionAssessment(
                active=True,
                session_name=None,
                phase="disabled",
                confidence_adjustment=0.0,
                risk_multiplier=1.0,
                reasons=(),
            )
        return assess_session(
            snapshot=snapshot,
            sessions_config=self.sessions_config,
            tuning_config=self.filter_config.session,
        )

    def _find_trigger_candidate(
        self,
        *,
        snapshot: MarketSnapshot,
        scanner_decision: ScannerDecision,
        execution_candle: Candle,
        side: Side,
        impulse_range: float,
    ) -> dict[str, object] | None:
        trigger_series = snapshot.series(self.trigger_timeframe)
        if not trigger_series:
            self.last_rejection_reason = f"missing {self.trigger_timeframe} trigger candles"
            return None

        if self.trigger_timeframe == self.execution_timeframe:
            candidates = (execution_candle,)
        else:
            candidates = tuple(
                candle
                for candle in trigger_series
                if candle.open_time >= execution_candle.open_time and candle.close_time <= execution_candle.close_time
            )
        if not candidates:
            self.last_rejection_reason = (
                f"no {self.trigger_timeframe} trigger candles found inside the current {self.execution_timeframe} bar"
            )
            return None

        last_error = "no valid trigger candle found"
        for candidate in candidates:
            evaluation = self._evaluate_trigger_candidate(
                snapshot=snapshot,
                scanner_decision=scanner_decision,
                trigger_candle=candidate,
                side=side,
                impulse_range=impulse_range,
            )
            if evaluation is not None:
                return evaluation
            if self.last_rejection_reason is not None:
                last_error = self.last_rejection_reason
        self.last_rejection_reason = last_error
        return None

    def _evaluate_trigger_candidate(
        self,
        *,
        snapshot: MarketSnapshot,
        scanner_decision: ScannerDecision,
        trigger_candle: Candle,
        side: Side,
        impulse_range: float,
    ) -> dict[str, object] | None:
        reference = self._reference_candles(
            trigger_series=snapshot.series(self.trigger_timeframe),
            trigger_candle=trigger_candle,
        )
        if not reference:
            self.last_rejection_reason = "not enough trigger reference candles"
            return None

        reference_mean_body = fmean(candle.body_size for candle in reference) if reference else 0.0
        trigger_body_ratio = safe_ratio(trigger_candle.body_size, reference_mean_body, default=0.0)
        trigger_close_position = close_position_for_side(trigger_candle, side)
        micro_tightness_score = self._micro_tightness_score(reference, impulse_range)
        pullback_tightness_ratio = float(scanner_decision.metrics.get("pullback_tightness_ratio", 1.0))
        pullback_tightness_score = max(0.0, min(1.0, 1.0 - pullback_tightness_ratio))
        pre_breakout_tightness_score = max(
            0.0,
            min(1.0, (pullback_tightness_score * 0.55) + (micro_tightness_score * 0.45)),
        )
        effective_max_body_ratio = self.trigger_config.max_body_ratio * (1.0 + micro_tightness_score)
        if self.trigger_timeframe != self.execution_timeframe:
            effective_max_body_ratio *= 1.35

        if side is Side.LONG:
            breakout_happened = trigger_candle.high > float(scanner_decision.trigger_level)
            breakout_confirmed = trigger_candle.close > float(scanner_decision.trigger_level)
            directional_candle = trigger_candle.is_bullish
            stop_buffer = trigger_candle.range_size * self.trigger_config.stop_buffer_ratio
            stop_price = float(scanner_decision.invalidation_level) - stop_buffer
            entry_price = trigger_candle.close
        else:
            breakout_happened = trigger_candle.low < float(scanner_decision.trigger_level)
            breakout_confirmed = trigger_candle.close < float(scanner_decision.trigger_level)
            directional_candle = not trigger_candle.is_bullish
            stop_buffer = trigger_candle.range_size * self.trigger_config.stop_buffer_ratio
            stop_price = float(scanner_decision.invalidation_level) + stop_buffer
            entry_price = trigger_candle.close

        breakout_extension_ratio = safe_ratio(
            abs(entry_price - float(scanner_decision.trigger_level)),
            impulse_range,
            default=0.0,
        )

        reasons: list[str] = []
        if not breakout_happened:
            self.last_rejection_reason = "trigger candle did not breach pullback structure"
            return None
        reasons.append("trigger candle breached the pullback structure")

        if self.trigger_config.require_breakout_close and not breakout_confirmed:
            self.last_rejection_reason = "trigger candle did not close beyond breakout level"
            return None
        if self.trigger_config.require_breakout_close:
            reasons.append("trigger candle closed beyond the breakout level")

        if not directional_candle:
            self.last_rejection_reason = "trigger candle did not close in trade direction"
            return None
        reasons.append("trigger candle closed in the direction of the trade")

        if trigger_body_ratio < self.trigger_config.min_body_ratio:
            self.last_rejection_reason = "trigger candle body expansion is too weak"
            return None
        reasons.append("trigger candle body expansion confirms resumed imbalance")

        if trigger_body_ratio > effective_max_body_ratio:
            self.last_rejection_reason = "trigger candle looks too extended or exhausted"
            return None
        reasons.append("trigger candle is not so extended that it looks exhausted")

        if trigger_close_position < self.trigger_config.min_close_position:
            self.last_rejection_reason = "trigger candle close is not near directional extreme"
            return None
        reasons.append("trigger candle close is near the directional extreme")

        if breakout_extension_ratio > self.trigger_config.max_breakout_extension_ratio:
            self.last_rejection_reason = "entry would chase too far beyond structure"
            return None
        reasons.append("entry is still close enough to structure to avoid late chase risk")

        if pre_breakout_tightness_score < self.trigger_config.min_pre_breakout_tightness_score:
            self.last_rejection_reason = "pre-trigger structure is not tight enough"
            return None
        reasons.append("breakout emerges from sufficiently tight pre-trigger structure")

        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit <= 0:
            self.last_rejection_reason = "risk per unit resolved to zero or invalid"
            return None
        first_target_price = entry_price + (risk_per_unit * side.multiplier)
        breakout_freshness_score = max(
            0.0,
            min(
                1.0,
                1.0
                - safe_ratio(
                    max(0.0, trigger_body_ratio - self.trigger_config.min_body_ratio),
                    max(1e-12, effective_max_body_ratio - self.trigger_config.min_body_ratio),
                    default=0.0,
                ),
            ),
        )
        extension_score = max(
            0.0,
            min(
                1.0,
                1.0
                - safe_ratio(
                    breakout_extension_ratio,
                    self.trigger_config.max_breakout_extension_ratio,
                    default=0.0,
                ),
            ),
        )
        entry_timing_score = max(
            0.0,
            min(
                1.0,
                (
                    breakout_freshness_score
                    + extension_score
                    + pre_breakout_tightness_score
                    + trigger_close_position
                )
                / 4.0,
            ),
        )
        return {
            "candle": trigger_candle,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "trigger_body_ratio": trigger_body_ratio,
            "trigger_close_position": trigger_close_position,
            "breakout_extension_ratio": breakout_extension_ratio,
            "pre_breakout_tightness_score": pre_breakout_tightness_score,
            "entry_timing_score": entry_timing_score,
            "first_target_price": first_target_price,
            "reasons": tuple(reasons),
            "effective_max_body_ratio": effective_max_body_ratio,
        }

    def _reference_candles(
        self,
        *,
        trigger_series: tuple[Candle, ...],
        trigger_candle: Candle,
    ) -> tuple[Candle, ...]:
        try:
            current_index = trigger_series.index(trigger_candle)
        except ValueError:
            return ()
        lookback = max(1, self.trigger_config.reference_lookback_bars)
        start_index = max(0, current_index - lookback)
        return trigger_series[start_index:current_index]

    def _micro_tightness_score(self, reference: tuple[Candle, ...], impulse_range: float) -> float:
        if not reference:
            return 0.0
        combined_range = max(candle.high for candle in reference) - min(candle.low for candle in reference)
        combined_range_ratio = safe_ratio(combined_range, impulse_range, default=1.0)
        average_range = fmean(candle.range_size for candle in reference) if reference else 0.0
        expansion_ratio = safe_ratio(
            combined_range,
            max(1e-12, average_range * max(1, len(reference))),
            default=1.0,
        )
        return max(
            0.0,
            min(
                1.0,
                (max(0.0, 1.0 - combined_range_ratio) * 0.65)
                + (max(0.0, 1.0 - expansion_ratio) * 0.35),
            ),
        )

    def _timeframe_delta(self, timeframe: str) -> timedelta:
        magnitude = int(timeframe[:-1])
        unit = timeframe[-1].lower()
        if unit == "m":
            return timedelta(minutes=magnitude)
        if unit == "h":
            return timedelta(hours=magnitude)
        raise ValueError(f"Unsupported timeframe: {timeframe}")
