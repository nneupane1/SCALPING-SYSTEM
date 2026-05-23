"""Test helpers for building candle fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.data.models import Candle


def utc_timestamp(hour: int, minute: int) -> datetime:
    return datetime(2026, 1, 5, hour, minute, tzinfo=timezone.utc)


def make_candle(
    *,
    minute_offset: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    timeframe: str = "15m",
    base_time: datetime | None = None,
) -> Candle:
    base = base_time or utc_timestamp(10, 0)
    open_time = base + timedelta(minutes=minute_offset)
    return Candle(
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15 if timeframe == "15m" else 1),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        trade_count=10,
        closed=True,
    )

