"""Bridges between pandas OHLCV frames and internal Candle tuples."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .models import Candle
from .resampler import timeframe_to_timedelta


def dataframe_to_candles(df: pd.DataFrame, *, symbol: str, timeframe: str) -> tuple[Candle, ...]:
    """Convert an OHLCV DataFrame into immutable closed Candle objects."""

    delta = timeframe_to_timedelta(timeframe)
    candles: list[Candle] = []
    for timestamp, row in df.iterrows():
        open_time = _to_datetime(timestamp)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=open_time + delta,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                trade_count=int(row.get("trade_count", 0)),
                closed=True,
            )
        )
    return tuple(candles)


def _to_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.to_pydatetime()
