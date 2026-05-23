"""Low-level scanner measurements."""

from __future__ import annotations

from statistics import fmean

from backend.app.core.models import Side
from backend.app.data.models import Candle

from .models import ImpulseAssessment, PullbackAssessment


def safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Return a stable ratio even when the denominator is zero."""

    if abs(denominator) <= 1e-12:
        return default
    return numerator / denominator


def average_body(candles: tuple[Candle, ...]) -> float:
    return fmean(candle.body_size for candle in candles) if candles else 0.0


def average_volume(candles: tuple[Candle, ...]) -> float:
    return fmean(candle.volume for candle in candles) if candles else 0.0


def close_position_for_side(candle: Candle, side: Side) -> float:
    """Measure where the close sits in the candle, aligned to trade direction."""

    return candle.close_position if side is Side.LONG else 1.0 - candle.close_position


def assess_impulse(
    candle: Candle,
    reference_candles: tuple[Candle, ...],
    min_body_ratio: float,
    min_volume_ratio: float,
) -> ImpulseAssessment:
    """Judge whether a candle represents meaningful expansion."""

    side = Side.LONG if candle.is_bullish else Side.SHORT
    body_ratio = safe_ratio(candle.body_size, average_body(reference_candles), default=0.0)
    volume_ratio = safe_ratio(candle.volume, average_volume(reference_candles), default=0.0)
    reasons: list[str] = []

    if body_ratio >= min_body_ratio:
        reasons.append("body expansion above threshold")
    else:
        reasons.append("body expansion below threshold")

    if volume_ratio >= min_volume_ratio:
        reasons.append("volume expansion above threshold")
    else:
        reasons.append("volume expansion below threshold")

    valid = body_ratio >= min_body_ratio and volume_ratio >= min_volume_ratio and candle.range_size > 0
    return ImpulseAssessment(
        valid=valid,
        side=side,
        body_ratio=body_ratio,
        volume_ratio=volume_ratio,
        reasons=tuple(reasons),
    )


def assess_pullback(
    side: Side,
    impulse_candle: Candle,
    pullback_candles: tuple[Candle, ...],
    max_depth_ratio: float,
    max_body_ratio: float,
) -> PullbackAssessment:
    """Judge whether the pause after momentum is controlled rather than chaotic."""

    if not pullback_candles:
        return PullbackAssessment(
            valid=False,
            retracement_depth_ratio=0.0,
            mean_body_ratio_to_impulse=0.0,
            orderliness_score=0.0,
            reasons=("pullback window is empty",),
        )

    impulse_range = max(impulse_candle.range_size, 1e-12)
    mean_body_ratio = safe_ratio(average_body(pullback_candles), impulse_candle.body_size, default=0.0)
    reasons: list[str] = []

    if side is Side.LONG:
        deepest_pullback = min(candle.low for candle in pullback_candles)
        retracement_depth = impulse_candle.high - deepest_pullback
        closes_inside_structure = all(candle.high <= impulse_candle.high for candle in pullback_candles)
        opposite_pressure = sum(1 for candle in pullback_candles if not candle.is_bullish)
    else:
        deepest_pullback = max(candle.high for candle in pullback_candles)
        retracement_depth = deepest_pullback - impulse_candle.low
        closes_inside_structure = all(candle.low >= impulse_candle.low for candle in pullback_candles)
        opposite_pressure = sum(1 for candle in pullback_candles if candle.is_bullish)

    retracement_depth_ratio = retracement_depth / impulse_range
    if retracement_depth_ratio <= max_depth_ratio:
        reasons.append("retracement depth remains controlled")
    else:
        reasons.append("retracement depth is too aggressive")

    if mean_body_ratio <= max_body_ratio:
        reasons.append("pullback candles are smaller than the impulse")
    else:
        reasons.append("pullback candles are too large relative to the impulse")

    if closes_inside_structure:
        reasons.append("pullback remains inside impulse structure")
    else:
        reasons.append("pullback violates impulse structure")

    direction_bias_score = opposite_pressure / len(pullback_candles)
    size_score = max(0.0, 1.0 - mean_body_ratio)
    depth_score = max(0.0, 1.0 - retracement_depth_ratio)
    orderliness_score = max(0.0, min(1.0, (direction_bias_score + size_score + depth_score) / 3))
    valid = (
        retracement_depth_ratio <= max_depth_ratio
        and mean_body_ratio <= max_body_ratio
        and closes_inside_structure
    )
    return PullbackAssessment(
        valid=valid,
        retracement_depth_ratio=retracement_depth_ratio,
        mean_body_ratio_to_impulse=mean_body_ratio,
        orderliness_score=orderliness_score,
        reasons=tuple(reasons),
    )

