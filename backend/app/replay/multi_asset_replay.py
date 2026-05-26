"""Merged deterministic replay across multiple symbols."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.core.models import MarketSnapshot
from backend.app.data.models import Candle


@dataclass
class MultiAssetReplayCursor:
    """Mutable replay cursor state for multiple execution series."""

    processed_steps: int = 0
    paused: bool = False


@dataclass(frozen=True)
class MultiAssetReplayStep:
    """One symbol snapshot inside a same-timestamp replay batch."""

    symbol: str
    clock_index: int
    execution_index: int | None
    execution_just_closed: bool
    snapshot: MarketSnapshot


class MultiAssetReplayEngine:
    """Emit batches of same-timestamp snapshots across multiple symbols."""

    def __init__(
        self,
        *,
        clock_timeframe: str,
        execution_timeframe: str,
        candles_by_symbol: dict[str, dict[str, tuple[Candle, ...]]],
    ) -> None:
        self.clock_timeframe = clock_timeframe
        self.execution_timeframe = execution_timeframe
        self.candles_by_symbol = candles_by_symbol
        self.indices: dict[str, int] = {symbol: 0 for symbol in candles_by_symbol}
        self.cursor = MultiAssetReplayCursor()
        self.total_steps = sum(
            len(series.get(clock_timeframe, ()))
            for series in candles_by_symbol.values()
        )

    def has_next(self) -> bool:
        if self.cursor.paused:
            return False
        for symbol, frames in self.candles_by_symbol.items():
            clock_series = frames.get(self.clock_timeframe, ())
            if self.indices[symbol] < len(clock_series):
                return True
        return False

    def step_batch(self) -> tuple[MultiAssetReplayStep, ...]:
        if not self.has_next():
            return ()

        next_times = []
        for symbol, frames in self.candles_by_symbol.items():
            clock_series = frames.get(self.clock_timeframe, ())
            index = self.indices[symbol]
            if index < len(clock_series):
                next_times.append(clock_series[index].close_time)
        if not next_times:
            return ()
        batch_close = min(next_times)

        snapshots: list[MultiAssetReplayStep] = []
        for symbol, frames in self.candles_by_symbol.items():
            clock_series = frames.get(self.clock_timeframe, ())
            index = self.indices[symbol]
            if index >= len(clock_series):
                continue
            clock_candle = clock_series[index]
            if clock_candle.close_time != batch_close:
                continue
            self.indices[symbol] += 1
            self.cursor.processed_steps += 1
            execution_series = frames.get(self.execution_timeframe, ())
            execution_index = None
            execution_just_closed = False
            for idx, execution_candle in enumerate(execution_series):
                if execution_candle.close_time > batch_close:
                    break
                execution_index = idx
                execution_just_closed = execution_candle.close_time == batch_close
            snapshots.append(
                MultiAssetReplayStep(
                    symbol=symbol,
                    clock_index=index,
                    execution_index=execution_index,
                    execution_just_closed=execution_just_closed,
                    snapshot=MarketSnapshot(
                        symbol=symbol,
                        generated_at=batch_close,
                        candles={
                            timeframe: tuple(candle for candle in series if candle.close_time <= batch_close)
                            for timeframe, series in frames.items()
                        },
                    ),
                )
            )
        return tuple(sorted(snapshots, key=lambda item: item.symbol))

    def reset(self) -> None:
        self.indices = {symbol: 0 for symbol in self.candles_by_symbol}
        self.cursor = MultiAssetReplayCursor()

    def latest_processed_at(self) -> datetime | None:
        processed_times: list[datetime] = []
        for symbol, frames in self.candles_by_symbol.items():
            execution_series = frames.get(self.clock_timeframe, ())
            index = self.indices[symbol]
            if index == 0 or not execution_series:
                continue
            processed_times.append(execution_series[index - 1].close_time)
        return max(processed_times) if processed_times else None
