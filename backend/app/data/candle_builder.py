"""Canonical `1m` candle construction from tick events."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from .models import Candle, CandleUpdate, Tick, candle_close_from_open


class CandleBuilder:
    """Convert a tick stream into deterministic candles.

    The builder intentionally fills minute gaps with zero-volume synthetic
    candles that repeat the last traded price. That choice keeps resampling and
    replay timing stable even when the raw event stream is sparse.
    """

    def __init__(self, symbol: str, timeframe: str = "1m") -> None:
        if timeframe != "1m":
            raise ValueError("The current CandleBuilder implementation supports only `1m` candles.")
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.delta = timedelta(minutes=1)
        self._active: Candle | None = None

    @property
    def active_candle(self) -> Candle | None:
        return None if self._active is None else replace(self._active)

    def update(self, tick: Tick) -> CandleUpdate:
        if tick.symbol.upper() != self.symbol:
            raise ValueError(f"Tick symbol {tick.symbol!r} does not match builder symbol {self.symbol!r}.")

        bucket_start = self._minute_floor(tick.event_time)
        if self._active is None:
            self._active = self._new_candle(bucket_start, tick.price, tick.quantity)
            return CandleUpdate(closed_candles=(), active_candle=replace(self._active))

        if bucket_start < self._active.open_time:
            raise ValueError("Out-of-order tick received by CandleBuilder.")

        if bucket_start == self._active.open_time:
            self._active.update(tick.price, tick.quantity)
            return CandleUpdate(closed_candles=(), active_candle=replace(self._active))

        closed_candles = self._roll_forward(bucket_start)
        self._active = self._new_candle(bucket_start, tick.price, tick.quantity)
        return CandleUpdate(
            closed_candles=tuple(closed_candles),
            active_candle=replace(self._active),
        )

    def _roll_forward(self, next_bucket_start: datetime) -> list[Candle]:
        assert self._active is not None
        closed: list[Candle] = []
        current = self._active
        current.close_time = candle_close_from_open(current.open_time, self.delta)
        current.closed = True
        closed.append(replace(current))

        gap_cursor = current.open_time + self.delta
        while gap_cursor < next_bucket_start:
            synthetic = Candle(
                symbol=self.symbol,
                timeframe=self.timeframe,
                open_time=gap_cursor,
                close_time=gap_cursor + self.delta,
                open=current.close,
                high=current.close,
                low=current.close,
                close=current.close,
                volume=0.0,
                trade_count=0,
                closed=True,
            )
            closed.append(synthetic)
            gap_cursor += self.delta
            current = synthetic
        return closed

    def _new_candle(self, open_time: datetime, price: float, quantity: float) -> Candle:
        return Candle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            open_time=open_time,
            close_time=open_time + self.delta,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=quantity,
            trade_count=1,
            closed=False,
        )

    def _minute_floor(self, timestamp: datetime) -> datetime:
        return timestamp.replace(second=0, microsecond=0)

