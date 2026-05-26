"""Deterministic historical replay."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.models import MarketSnapshot
from backend.app.data.models import Candle


@dataclass
class ReplayCursor:
    """Mutable replay cursor state."""

    index: int = 0
    paused: bool = False


class ReplayEngine:
    """Emit historical snapshots one execution candle at a time."""

    def __init__(
        self,
        *,
        symbol: str,
        clock_timeframe: str,
        execution_timeframe: str,
        candles_by_timeframe: dict[str, tuple[Candle, ...]],
    ) -> None:
        self.symbol = symbol
        self.clock_timeframe = clock_timeframe
        self.execution_timeframe = execution_timeframe
        self.candles_by_timeframe = candles_by_timeframe
        self.cursor = ReplayCursor()

    def has_next(self) -> bool:
        clock_series = self.candles_by_timeframe.get(self.clock_timeframe, ())
        return self.cursor.index < len(clock_series)

    def step(self) -> MarketSnapshot | None:
        if self.cursor.paused or not self.has_next():
            return None
        clock_series = self.candles_by_timeframe[self.clock_timeframe]
        clock_candle = clock_series[self.cursor.index]
        self.cursor.index += 1
        visible_until = clock_candle.close_time
        candles = {
            timeframe: tuple(candle for candle in series if candle.close_time <= visible_until)
            for timeframe, series in self.candles_by_timeframe.items()
        }
        return MarketSnapshot(
            symbol=self.symbol,
            generated_at=clock_candle.close_time,
            candles=candles,
        )

    def reset(self) -> None:
        self.cursor = ReplayCursor()
