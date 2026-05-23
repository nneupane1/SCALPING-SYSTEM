"""Higher-timeframe candle rebuilding from canonical base candles."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .models import Candle


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    """Convert a timeframe string such as `1m`, `15m`, or `1h` into a timedelta."""

    if len(timeframe) < 2:
        raise ValueError(f"Invalid timeframe: {timeframe}")
    unit = timeframe[-1].lower()
    magnitude = int(timeframe[:-1])
    if unit == "m":
        return timedelta(minutes=magnitude)
    if unit == "h":
        return timedelta(hours=magnitude)
    raise ValueError(f"Unsupported timeframe unit: {timeframe}")


def floor_timestamp(timestamp: datetime, timeframe: str) -> datetime:
    """Floor a timestamp to the start of the containing timeframe bucket."""

    delta = timeframe_to_timedelta(timeframe)
    epoch_seconds = int(timestamp.timestamp())
    bucket_seconds = int(delta.total_seconds())
    floored = epoch_seconds - (epoch_seconds % bucket_seconds)
    return datetime.fromtimestamp(floored, tz=timestamp.tzinfo)


class TimeframeResampler:
    """Resample canonical `1m` candles into higher-timeframe bars."""

    def __init__(self, base_timeframe: str = "1m") -> None:
        self.base_timeframe = base_timeframe
        self.base_delta = timeframe_to_timedelta(base_timeframe)

    def resample(self, candles: tuple[Candle, ...], target_timeframe: str) -> tuple[Candle, ...]:
        if target_timeframe == self.base_timeframe:
            return tuple(candle.closed_copy() for candle in candles if candle.closed)

        target_delta = timeframe_to_timedelta(target_timeframe)
        base_seconds = int(self.base_delta.total_seconds())
        target_seconds = int(target_delta.total_seconds())
        if target_seconds % base_seconds != 0:
            raise ValueError("Target timeframe must be an integer multiple of the base timeframe.")

        expected_count = target_seconds // base_seconds
        grouped: dict[datetime, list[Candle]] = defaultdict(list)
        for candle in candles:
            if not candle.closed:
                continue
            grouped[floor_timestamp(candle.open_time, target_timeframe)].append(candle)

        result: list[Candle] = []
        for bucket_start in sorted(grouped):
            group = sorted(grouped[bucket_start], key=lambda candle: candle.open_time)
            if len(group) != expected_count:
                continue
            if not self._group_is_contiguous(group):
                continue
            result.append(
                Candle(
                    symbol=group[0].symbol,
                    timeframe=target_timeframe,
                    open_time=bucket_start,
                    close_time=bucket_start + target_delta,
                    open=group[0].open,
                    high=max(candle.high for candle in group),
                    low=min(candle.low for candle in group),
                    close=group[-1].close,
                    volume=sum(candle.volume for candle in group),
                    trade_count=sum(candle.trade_count for candle in group),
                    closed=True,
                )
            )
        return tuple(result)

    def _group_is_contiguous(self, group: list[Candle]) -> bool:
        for previous, current in zip(group, group[1:]):
            if current.open_time - previous.open_time != self.base_delta:
                return False
        return True

