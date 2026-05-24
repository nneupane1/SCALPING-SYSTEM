"""Momentum -> pullback -> re-expansion strategy."""

from __future__ import annotations

from statistics import fmean

from backend.app.config.models import (
    SessionsConfig,
    StrategyFilterConfig,
    StrategyRuleConfig,
    StrategyTriggerConfig,
    TimeframeProfileConfig,
)
from backend.app.core.models import MarketSnapshot, ScannerDecision, Side, TradeSignal
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
        self.profile = profile
        self.sessions_config = sessions_config

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

        context = assess_context(
            snapshot=snapshot,
            side=side,
            config=self.filter_config.context,
        )
        session = self._assess_session(snapshot)
        if not session.active:
            return None
        market_state = assess_market_state(
            snapshot=snapshot,
            side=side,
            config=self.filter_config.market_state,
            execution_timeframe=self.execution_timeframe,
        )
        if market_state.no_trade:
            return None
        if context.alignment == "conflicting" and self.filter_config.context.block_on_conflict:
            return None

        quality = assess_setup_quality(
            scanner_decision=scanner_decision,
            trigger_body_ratio=trigger_body_ratio,
            trigger_close_position=trigger_close_position,
            context=context,
            market_state=market_state,
            session=session,
            config=self.filter_config.quality,
        )
        if self.filter_config.quality.enabled and quality.label == "reject":
            return None

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
                "risk_fraction_multiplier": combined_risk_multiplier,
                "trigger_body_ratio": trigger_body_ratio,
                "trigger_close_position": trigger_close_position,
                "scanner_momentum_score": scanner_decision.momentum_score,
                "scanner_pullback_score": scanner_decision.pullback_score,
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
