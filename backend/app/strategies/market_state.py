"""Market-state classification for execution-timeframe signal quality."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from backend.app.config.models import StrategyFilterConfig
from backend.app.core.models import MarketSnapshot, Side
from backend.app.data.models import Candle


@dataclass(frozen=True)
class MarketStateAssessment:
    """Interpret the broader environment around a candidate trade."""

    timeframe: str
    state: str
    available: bool
    alignment: str
    no_trade: bool
    efficiency: float
    overlap_ratio: float
    alternation_ratio: float
    compression_ratio: float
    confidence_adjustment: float
    risk_multiplier: float
    reasons: tuple[str, ...]


def assess_market_state(
    *,
    snapshot: MarketSnapshot,
    side: Side,
    config: StrategyFilterConfig.MarketStateConfig,
    execution_timeframe: str,
) -> MarketStateAssessment:
    """Classify the market as trend, transition, range, chop, or compression."""

    if not config.enabled:
        return MarketStateAssessment(
            timeframe=config.timeframe,
            state="disabled",
            available=False,
            alignment="neutral",
            no_trade=False,
            efficiency=0.0,
            overlap_ratio=0.0,
            alternation_ratio=0.0,
            compression_ratio=1.0,
            confidence_adjustment=0.0,
            risk_multiplier=1.0,
            reasons=(),
        )

    context_window = snapshot.series(config.timeframe)[-config.context_lookback_bars :]
    execution_window = snapshot.series(execution_timeframe)[-config.execution_lookback_bars :]
    if len(context_window) < max(3, config.context_lookback_bars) or len(execution_window) < max(3, config.execution_lookback_bars):
        return MarketStateAssessment(
            timeframe=config.timeframe,
            state="unavailable",
            available=False,
            alignment="neutral",
            no_trade=False,
            efficiency=0.0,
            overlap_ratio=0.0,
            alternation_ratio=0.0,
            compression_ratio=1.0,
            confidence_adjustment=0.0,
            risk_multiplier=1.0,
            reasons=(f"not enough {config.timeframe} / {execution_timeframe} candles for market-state assessment",),
        )

    efficiency = _directional_efficiency(context_window, side)
    overlap_ratio = _average_overlap_ratio(execution_window)
    alternation_ratio = _alternation_ratio(execution_window)
    compression_ratio = _compression_ratio(context_window)
    opposing_efficiency = _directional_efficiency(
        context_window,
        Side.SHORT if side is Side.LONG else Side.LONG,
    )

    if compression_ratio <= config.compression_ratio_threshold and overlap_ratio >= 0.45:
        state = "compression"
    elif efficiency >= config.trend_efficiency_threshold and overlap_ratio < config.chop_overlap_threshold:
        state = "trend"
    elif alternation_ratio >= config.alternation_threshold or overlap_ratio >= config.chop_overlap_threshold:
        state = "volatile_chop"
    elif efficiency <= config.trend_efficiency_threshold * 0.5:
        state = "range"
    else:
        state = "transition"

    alignment = "aligned"
    if state == "trend" and opposing_efficiency > efficiency:
        alignment = "conflicting"
    elif state in {"range", "transition", "compression"}:
        alignment = "neutral"
    elif state == "volatile_chop":
        alignment = "conflicting"

    reasons = [
        f"{config.timeframe} market state classified as {state}",
        f"directional efficiency {efficiency:.2f} | overlap {overlap_ratio:.2f} | alternation {alternation_ratio:.2f}",
    ]
    no_trade = state in set(config.no_trade_states)

    if state == "trend" and alignment == "aligned":
        return MarketStateAssessment(
            timeframe=config.timeframe,
            state=state,
            available=True,
            alignment=alignment,
            no_trade=no_trade,
            efficiency=efficiency,
            overlap_ratio=overlap_ratio,
            alternation_ratio=alternation_ratio,
            compression_ratio=compression_ratio,
            confidence_adjustment=config.trend_confidence_bonus,
            risk_multiplier=config.trend_risk_multiplier,
            reasons=tuple(reasons + ["broader structure supports continuation"]),
        )
    if state == "transition":
        return MarketStateAssessment(
            timeframe=config.timeframe,
            state=state,
            available=True,
            alignment=alignment,
            no_trade=no_trade,
            efficiency=efficiency,
            overlap_ratio=overlap_ratio,
            alternation_ratio=alternation_ratio,
            compression_ratio=compression_ratio,
            confidence_adjustment=config.transition_confidence_adjustment,
            risk_multiplier=config.transition_risk_multiplier,
            reasons=tuple(reasons + ["broader structure is transitioning rather than clearly trending"]),
        )
    if state == "range":
        return MarketStateAssessment(
            timeframe=config.timeframe,
            state=state,
            available=True,
            alignment=alignment,
            no_trade=no_trade,
            efficiency=efficiency,
            overlap_ratio=overlap_ratio,
            alternation_ratio=alternation_ratio,
            compression_ratio=compression_ratio,
            confidence_adjustment=-config.range_confidence_penalty,
            risk_multiplier=config.range_risk_multiplier,
            reasons=tuple(reasons + ["broader structure is ranging and continuation quality is reduced"]),
        )
    if state == "volatile_chop":
        return MarketStateAssessment(
            timeframe=config.timeframe,
            state=state,
            available=True,
            alignment=alignment,
            no_trade=no_trade,
            efficiency=efficiency,
            overlap_ratio=overlap_ratio,
            alternation_ratio=alternation_ratio,
            compression_ratio=compression_ratio,
            confidence_adjustment=-config.chop_confidence_penalty,
            risk_multiplier=config.chop_risk_multiplier,
            reasons=tuple(reasons + ["overlap and alternation indicate noisy chop"]),
        )
    return MarketStateAssessment(
        timeframe=config.timeframe,
        state=state,
        available=True,
        alignment=alignment,
        no_trade=no_trade,
        efficiency=efficiency,
        overlap_ratio=overlap_ratio,
        alternation_ratio=alternation_ratio,
        compression_ratio=compression_ratio,
        confidence_adjustment=-config.compression_confidence_penalty,
        risk_multiplier=config.compression_risk_multiplier,
        reasons=tuple(reasons + ["broader structure is compressed and not yet expanding cleanly"]),
    )


def _directional_efficiency(window: tuple[Candle, ...], side: Side) -> float:
    if len(window) < 2:
        return 0.0
    total_range = sum(max(candle.range_size, 1e-12) for candle in window)
    net_move = (window[-1].close - window[0].open) * side.multiplier
    return max(0.0, net_move / total_range)


def _average_overlap_ratio(window: tuple[Candle, ...]) -> float:
    overlaps: list[float] = []
    for previous, current in zip(window, window[1:]):
        upper = min(previous.high, current.high)
        lower = max(previous.low, current.low)
        overlap = max(0.0, upper - lower)
        union = max(previous.high, current.high) - min(previous.low, current.low)
        overlaps.append(0.0 if union <= 1e-12 else overlap / union)
    return fmean(overlaps) if overlaps else 0.0


def _alternation_ratio(window: tuple[Candle, ...]) -> float:
    switches = 0
    comparisons = 0
    for previous, current in zip(window, window[1:]):
        comparisons += 1
        if previous.is_bullish != current.is_bullish:
            switches += 1
    return switches / comparisons if comparisons else 0.0


def _compression_ratio(window: tuple[Candle, ...]) -> float:
    if len(window) < 4:
        return 1.0
    split = len(window) // 2
    first_half = window[:split]
    second_half = window[split:]
    first_average = fmean(max(candle.range_size, 1e-12) for candle in first_half)
    second_average = fmean(max(candle.range_size, 1e-12) for candle in second_half)
    return second_average / first_average if first_average > 1e-12 else 1.0
