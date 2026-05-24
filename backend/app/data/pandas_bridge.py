"""Bridges between pandas OHLCV frames and internal Candle tuples."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .models import Candle
from .resampler import timeframe_to_timedelta


def dataframe_to_candles(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    index_is_close_time: bool = False,
) -> tuple[Candle, ...]:
    """Convert an OHLCV DataFrame into immutable closed Candle objects."""

    delta = timeframe_to_timedelta(timeframe)
    candles: list[Candle] = []
    for timestamp, row in df.iterrows():
        open_or_close_time = _to_datetime(timestamp)
        if index_is_close_time:
            close_time = open_or_close_time
            open_time = close_time - delta
        else:
            open_time = open_or_close_time
            close_time = open_time + delta
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                trade_count=_coerce_trade_count(row.get("trade_count", 0)),
                closed=True,
            )
        )
    return tuple(candles)


def _to_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime().astimezone(timezone.utc)


def _coerce_trade_count(value: object) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)
