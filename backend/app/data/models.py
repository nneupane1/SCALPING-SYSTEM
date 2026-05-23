"""Market data models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Tick:
    """A raw market-data event used to build candles."""

    symbol: str
    price: float
    quantity: float
    event_time: datetime


@dataclass
class Candle:
    """A mutable OHLCV candle.

    The system keeps candle objects explicit and inspectable instead of using a
    DataFrame-only representation in the core runtime. That makes unit testing
    and event-by-event replay easier.
    """

    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int = 0
    closed: bool = False

    @property
    def range_size(self) -> float:
        return self.high - self.low

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def close_position(self) -> float:
        if self.range_size <= 0:
            return 0.5
        return (self.close - self.low) / self.range_size

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    def update(self, price: float, quantity: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += quantity
        self.trade_count += 1

    def closed_copy(self) -> "Candle":
        return replace(self, closed=True)


@dataclass(frozen=True)
class CandleUpdate:
    """Result of one candle-builder update call."""

    closed_candles: tuple[Candle, ...]
    active_candle: Candle


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def candle_close_from_open(open_time: datetime, timeframe_delta: timedelta) -> datetime:
    """Compute the close timestamp from the open timestamp and timeframe size."""

    return open_time + timeframe_delta

