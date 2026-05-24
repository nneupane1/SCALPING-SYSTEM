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


def average_range(candles: tuple[Candle, ...]) -> float:
    return fmean(candle.range_size for candle in candles) if candles else 0.0


def close_position_for_side(candle: Candle, side: Side) -> float:
    """Measure where the close sits in the candle, aligned to trade direction."""

    return candle.close_position if side is Side.LONG else 1.0 - candle.close_position


def overlap_ratio(left: Candle, right: Candle) -> float:
    """Measure how much two candle ranges overlap relative to the smaller range."""

    left_range = max(left.range_size, 1e-12)
    right_range = max(right.range_size, 1e-12)
    shared = max(0.0, min(left.high, right.high) - max(left.low, right.low))
    return shared / min(left_range, right_range)


def assess_impulse(
    candle: Candle,
    reference_candles: tuple[Candle, ...],
    min_body_ratio: float,
    min_volume_ratio: float,
    min_range_ratio: float,
    min_close_position: float,
    min_efficiency: float,
    strong_body_ratio: float,
    strong_volume_ratio: float,
    explosive_body_ratio: float,
    explosive_volume_ratio: float,
) -> ImpulseAssessment:
    """Judge whether a candle represents meaningful expansion."""

    side = Side.LONG if candle.is_bullish else Side.SHORT
    body_ratio = safe_ratio(candle.body_size, average_body(reference_candles), default=0.0)
    volume_ratio = safe_ratio(candle.volume, average_volume(reference_candles), default=0.0)
    range_ratio = safe_ratio(candle.range_size, average_range(reference_candles), default=0.0)
    directional_close_position = close_position_for_side(candle, side)
    efficiency = safe_ratio(candle.body_size, candle.range_size, default=0.0)
    reasons: list[str] = []

    if body_ratio >= min_body_ratio:
        reasons.append("body expansion above threshold")
    else:
        reasons.append("body expansion below threshold")

    if volume_ratio >= min_volume_ratio:
        reasons.append("volume expansion above threshold")
    else:
        reasons.append("volume expansion below threshold")

    if range_ratio >= min_range_ratio:
        reasons.append("range expansion confirms directional participation")
    else:
        reasons.append("range expansion is too small for a meaningful impulse")

    if directional_close_position >= min_close_position:
        reasons.append("impulse closes near the directional extreme")
    else:
        reasons.append("impulse close is too weak for continuation quality")

    if efficiency >= min_efficiency:
        reasons.append("impulse candle is efficient rather than wick-heavy")
    else:
        reasons.append("impulse candle is too inefficient or wick-heavy")

    quality_score = max(
        0.0,
        min(
            1.0,
            (
                min(2.5, body_ratio) / 2.5
                + min(2.0, volume_ratio) / 2.0
                + min(2.0, range_ratio) / 2.0
                + directional_close_position
                + efficiency
            )
            / 5.0,
        ),
    )

    if body_ratio >= explosive_body_ratio and volume_ratio >= explosive_volume_ratio and quality_score >= 0.86:
        tier = "explosive"
    elif body_ratio >= strong_body_ratio and volume_ratio >= strong_volume_ratio and quality_score >= 0.72:
        tier = "strong"
    elif quality_score >= 0.58:
        tier = "average"
    else:
        tier = "weak"

    valid = (
        body_ratio >= min_body_ratio
        and volume_ratio >= min_volume_ratio
        and range_ratio >= min_range_ratio
        and directional_close_position >= min_close_position
        and efficiency >= min_efficiency
        and candle.range_size > 0
    )
    return ImpulseAssessment(
        valid=valid,
        side=side,
        body_ratio=body_ratio,
        volume_ratio=volume_ratio,
        range_ratio=range_ratio,
        close_position=directional_close_position,
        efficiency=efficiency,
        quality_score=quality_score,
        tier=tier,
        reasons=tuple(reasons),
    )


def assess_pullback(
    side: Side,
    impulse_candle: Candle,
    pullback_candles: tuple[Candle, ...],
    max_depth_ratio: float,
    max_body_ratio: float,
    max_range_ratio: float,
    min_overlap_ratio: float,
) -> PullbackAssessment:
    """Judge whether the pause after momentum is controlled rather than chaotic."""

    if not pullback_candles:
        return PullbackAssessment(
            valid=False,
            retracement_depth_ratio=0.0,
            mean_body_ratio_to_impulse=0.0,
            overlap_ratio=0.0,
            tightness_ratio=0.0,
            counter_pressure_ratio=0.0,
            orderliness_score=0.0,
            quality_label="invalid",
            reasons=("pullback window is empty",),
        )

    impulse_range = max(impulse_candle.range_size, 1e-12)
    mean_body_ratio = safe_ratio(average_body(pullback_candles), impulse_candle.body_size, default=0.0)
    tightness_ratio = safe_ratio(average_range(pullback_candles), impulse_range, default=0.0)
    reasons: list[str] = []

    if side is Side.LONG:
        deepest_pullback = min(candle.low for candle in pullback_candles)
        retracement_depth = impulse_candle.high - deepest_pullback
        closes_inside_structure = all(candle.high <= impulse_candle.high for candle in pullback_candles)
        counter_pressure = sum(1 for candle in pullback_candles if not candle.is_bullish)
    else:
        deepest_pullback = max(candle.high for candle in pullback_candles)
        retracement_depth = deepest_pullback - impulse_candle.low
        closes_inside_structure = all(candle.low >= impulse_candle.low for candle in pullback_candles)
        counter_pressure = sum(1 for candle in pullback_candles if candle.is_bullish)

    retracement_depth_ratio = retracement_depth / impulse_range
    if retracement_depth_ratio <= max_depth_ratio:
        reasons.append("retracement depth remains controlled")
    else:
        reasons.append("retracement depth is too aggressive")

    if mean_body_ratio <= max_body_ratio:
        reasons.append("pullback candles are smaller than the impulse")
    else:
        reasons.append("pullback candles are too large relative to the impulse")

    if tightness_ratio <= max_range_ratio:
        reasons.append("pullback ranges stay compressed relative to the impulse")
    else:
        reasons.append("pullback ranges expand too much for a clean reset")

    if closes_inside_structure:
        reasons.append("pullback remains inside impulse structure")
    else:
        reasons.append("pullback violates impulse structure")

    pair_overlaps = tuple(
        overlap_ratio(pullback_candles[index - 1], pullback_candles[index])
        for index in range(1, len(pullback_candles))
    )
    overlap_score = fmean(pair_overlaps) if pair_overlaps else 1.0
    counter_pressure_ratio = counter_pressure / len(pullback_candles)
    if overlap_score >= min_overlap_ratio:
        reasons.append("pullback candles overlap enough to show orderly digestion")
    else:
        reasons.append("pullback lacks overlap and looks too fragmented")

    depth_score = max(0.0, 1.0 - retracement_depth_ratio)
    body_score = max(0.0, 1.0 - mean_body_ratio)
    tightness_score = max(0.0, 1.0 - tightness_ratio)
    overlap_score_clamped = max(0.0, min(1.0, overlap_score))
    orderliness_score = max(
        0.0,
        min(
            1.0,
            (
                depth_score
                + body_score
                + tightness_score
                + overlap_score_clamped
                + counter_pressure_ratio
            )
            / 5.0,
        ),
    )
    if (
        retracement_depth_ratio <= max_depth_ratio * 0.7
        and mean_body_ratio <= max_body_ratio * 0.75
        and tightness_ratio <= max_range_ratio * 0.85
        and overlap_score >= max(min_overlap_ratio, 0.3)
        and closes_inside_structure
    ):
        quality_label = "clean"
    elif closes_inside_structure and retracement_depth_ratio <= max_depth_ratio and mean_body_ratio <= max_body_ratio:
        quality_label = "neutral"
    else:
        quality_label = "aggressive"

    valid = (
        retracement_depth_ratio <= max_depth_ratio
        and mean_body_ratio <= max_body_ratio
        and tightness_ratio <= max_range_ratio
        and overlap_score >= min_overlap_ratio
        and closes_inside_structure
    )
    return PullbackAssessment(
        valid=valid,
        retracement_depth_ratio=retracement_depth_ratio,
        mean_body_ratio_to_impulse=mean_body_ratio,
        overlap_ratio=overlap_score,
        tightness_ratio=tightness_ratio,
        counter_pressure_ratio=counter_pressure_ratio,
        orderliness_score=orderliness_score,
        quality_label=quality_label,
        reasons=tuple(reasons),
    )
