"""Momentum and pullback scanner."""

from __future__ import annotations

from backend.app.config.models import ScannerConfig
from backend.app.core.models import MarketSnapshot, ScannerDecision, ScannerState, Side

from .filters import assess_impulse, assess_pullback


class MomentumScanner:
    """Detect momentum plus orderly pullback sequences.

    The scanner deliberately does not place trades. Its job is narrower:
    identify whether recent candles describe a coherent narrative that the
    strategy is even allowed to consider.
    """

    def __init__(
        self,
        scanner_config: ScannerConfig,
        execution_timeframe: str,
        profile_name: str = "default",
    ) -> None:
        self.config = scanner_config
        self.execution_timeframe = execution_timeframe
        self.profile_name = profile_name

    def scan(self, snapshot: MarketSnapshot) -> ScannerDecision:
        candles = snapshot.series(self.execution_timeframe)
        minimum_bars = self.config.max_pullback_bars + 2
        if len(candles) < minimum_bars:
            return ScannerDecision(
                state=ScannerState.INACTIVE,
                side=None,
                impulse_candle=None,
                pullback_candles=(),
                trigger_level=None,
                invalidation_level=None,
                momentum_score=0.0,
                pullback_score=0.0,
                reasons=("not enough closed candles for scanner evaluation",),
                metrics={},
            )

        found_impulse = False
        best_decision: ScannerDecision | None = None

        for pullback_bars in range(self.config.min_pullback_bars, self.config.max_pullback_bars + 1):
            required = pullback_bars + 2
            if len(candles) < required:
                continue

            impulse_candle = candles[-required]
            pullback_candles = candles[-required + 1 : -1]
            reference_start = max(0, len(candles) - required - self.config.compression_lookback)
            reference_candles = candles[reference_start : len(candles) - required]
            if not reference_candles:
                continue

            impulse = assess_impulse(
                candle=impulse_candle,
                reference_candles=reference_candles,
                min_body_ratio=self.config.min_impulse_body_ratio,
                min_volume_ratio=self.config.min_volume_ratio,
                min_range_ratio=self.config.min_impulse_range_ratio,
                min_close_position=self.config.min_impulse_close_position,
                min_efficiency=self.config.min_impulse_efficiency,
                strong_body_ratio=self.config.strong_impulse_body_ratio,
                strong_volume_ratio=self.config.strong_impulse_volume_ratio,
                explosive_body_ratio=self.config.explosive_impulse_body_ratio,
                explosive_volume_ratio=self.config.explosive_impulse_volume_ratio,
            )
            if not impulse.valid:
                continue

            found_impulse = True
            pullback = assess_pullback(
                side=impulse.side,
                impulse_candle=impulse_candle,
                pullback_candles=pullback_candles,
                max_depth_ratio=self.config.max_pullback_depth_ratio,
                max_body_ratio=self.config.max_pullback_body_ratio,
                max_range_ratio=self.config.max_pullback_range_ratio,
                min_overlap_ratio=self.config.min_pullback_overlap_ratio,
            )
            if not pullback.valid:
                continue

            if impulse.side is Side.LONG:
                trigger_level = max(candle.high for candle in pullback_candles)
                invalidation_level = min(candle.low for candle in pullback_candles)
            else:
                trigger_level = min(candle.low for candle in pullback_candles)
                invalidation_level = max(candle.high for candle in pullback_candles)

            reasons = tuple(impulse.reasons + pullback.reasons)
            momentum_score = max(
                0.0,
                min(
                    1.0,
                    (
                        impulse.quality_score
                        + min(1.0, impulse.body_ratio / max(self.config.strong_impulse_body_ratio, 1e-12))
                        + min(1.0, impulse.volume_ratio / max(self.config.strong_impulse_volume_ratio, 1e-12))
                    )
                    / 3.0,
                ),
            )
            setup_score = (momentum_score * 0.52) + (pullback.orderliness_score * 0.48)
            candidate = ScannerDecision(
                state=ScannerState.READY,
                side=impulse.side,
                impulse_candle=impulse_candle,
                pullback_candles=pullback_candles,
                trigger_level=trigger_level,
                invalidation_level=invalidation_level,
                momentum_score=momentum_score,
                pullback_score=pullback.orderliness_score,
                reasons=reasons,
                metrics={
                    "profile_timeframe_value": float(self.execution_timeframe.rstrip("mh")),
                    "scanner_setup_score": setup_score,
                    "impulse_quality_score": impulse.quality_score,
                    "impulse_tier": impulse.tier,
                    "impulse_body_ratio": impulse.body_ratio,
                    "impulse_volume_ratio": impulse.volume_ratio,
                    "impulse_range_ratio": impulse.range_ratio,
                    "impulse_close_position": impulse.close_position,
                    "impulse_efficiency": impulse.efficiency,
                    "pullback_depth_ratio": pullback.retracement_depth_ratio,
                    "pullback_body_ratio": pullback.mean_body_ratio_to_impulse,
                    "pullback_overlap_ratio": pullback.overlap_ratio,
                    "pullback_tightness_ratio": pullback.tightness_ratio,
                    "pullback_counter_pressure_ratio": pullback.counter_pressure_ratio,
                    "pullback_orderliness_score": pullback.orderliness_score,
                    "pullback_quality_label": pullback.quality_label,
                    "pullback_bars": float(pullback_bars),
                },
            )
            if (
                best_decision is None
                or float(candidate.metrics["scanner_setup_score"]) > float(best_decision.metrics["scanner_setup_score"])
            ):
                best_decision = candidate

        if best_decision is not None:
            return best_decision

        state = ScannerState.IMPULSE_FOUND if found_impulse else ScannerState.INACTIVE
        reason = "impulse found but pullback invalid" if found_impulse else "no valid impulse detected"
        return ScannerDecision(
            state=state,
            side=None,
            impulse_candle=None,
            pullback_candles=(),
            trigger_level=None,
            invalidation_level=None,
            momentum_score=0.0,
            pullback_score=0.0,
            reasons=(reason,),
            metrics={},
        )
