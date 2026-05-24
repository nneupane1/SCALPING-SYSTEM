"""Higher-timeframe context helpers for execution-timeframe signals."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.config.models import StrategyFilterConfig
from backend.app.core.models import MarketSnapshot, Side
from backend.app.data.models import Candle


@dataclass(frozen=True)
class ContextAssessment:
    """Soft context interpretation for one trade direction."""

    timeframe: str
    available: bool
    alignment: str
    support_score: float
    opposing_score: float
    reasons: tuple[str, ...]
    confidence_adjustment: float
    risk_multiplier: float


def assess_context(
    *,
    snapshot: MarketSnapshot,
    side: Side,
    config: StrategyFilterConfig.ContextConfig,
) -> ContextAssessment:
    """Interpret a slower timeframe as guidance rather than a hard block."""

    if not config.enabled:
        return ContextAssessment(
            timeframe=config.timeframe,
            available=False,
            alignment="disabled",
            support_score=0.0,
            opposing_score=0.0,
            reasons=(),
            confidence_adjustment=0.0,
            risk_multiplier=1.0,
        )

    candles = snapshot.series(config.timeframe)
    if len(candles) < max(2, config.lookback_bars):
        return ContextAssessment(
            timeframe=config.timeframe,
            available=False,
            alignment="unavailable",
            support_score=0.0,
            opposing_score=0.0,
            reasons=(f"not enough {config.timeframe} context candles",),
            confidence_adjustment=0.0,
            risk_multiplier=1.0,
        )

    window = candles[-config.lookback_bars :]
    long_score = _direction_score(window, Side.LONG)
    short_score = _direction_score(window, Side.SHORT)

    if side is Side.LONG:
        support_score = long_score
        opposing_score = short_score
    else:
        support_score = short_score
        opposing_score = long_score

    margin = support_score - opposing_score
    if support_score >= config.alignment_threshold and margin >= config.clear_margin:
        return ContextAssessment(
            timeframe=config.timeframe,
            available=True,
            alignment="aligned",
            support_score=support_score,
            opposing_score=opposing_score,
            reasons=(
                f"{config.timeframe} context supports continuation",
                f"{config.timeframe} structure is aligned with the execution-side bias",
            ),
            confidence_adjustment=config.confidence_bonus,
            risk_multiplier=config.aligned_risk_multiplier,
        )

    if opposing_score >= config.alignment_threshold and -margin >= config.clear_margin:
        return ContextAssessment(
            timeframe=config.timeframe,
            available=True,
            alignment="conflicting",
            support_score=support_score,
            opposing_score=opposing_score,
            reasons=(
                f"{config.timeframe} context is pushing against the execution-side bias",
                f"{config.timeframe} structure looks noisy or counter-directional for continuation",
            ),
            confidence_adjustment=-config.confidence_penalty,
            risk_multiplier=config.conflicting_risk_multiplier,
        )

    return ContextAssessment(
        timeframe=config.timeframe,
        available=True,
        alignment="neutral",
        support_score=support_score,
        opposing_score=opposing_score,
        reasons=(
            f"{config.timeframe} context is mixed",
            f"{config.timeframe} structure does not strongly confirm or reject continuation",
        ),
        confidence_adjustment=-config.neutral_confidence_penalty,
        risk_multiplier=config.neutral_risk_multiplier,
    )


def _direction_score(window: tuple[Candle, ...], side: Side) -> float:
    pair_count = len(window) - 1
    if pair_count <= 0:
        return 0.5

    advancing_highs = 0
    advancing_lows = 0
    advancing_closes = 0
    for previous, current in zip(window, window[1:]):
        if side is Side.LONG:
            advancing_highs += int(current.high >= previous.high)
            advancing_lows += int(current.low >= previous.low)
            advancing_closes += int(current.close >= previous.close)
        else:
            advancing_highs += int(current.high <= previous.high)
            advancing_lows += int(current.low <= previous.low)
            advancing_closes += int(current.close <= previous.close)

    latest = window[-1]
    range_extreme_score = latest.close_position if side is Side.LONG else (1.0 - latest.close_position)
    pair_score = (advancing_highs / pair_count + advancing_lows / pair_count + advancing_closes / pair_count) / 3
    return max(0.0, min(1.0, (pair_score * 0.75) + (range_extreme_score * 0.25)))
