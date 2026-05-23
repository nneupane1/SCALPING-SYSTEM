"""In-memory candle caches."""

from __future__ import annotations

from collections import deque
from typing import Iterable

from .models import Candle


class CandleCache:
    """A bounded per-timeframe candle cache."""

    def __init__(self, limit: int = 5000) -> None:
        self.limit = limit
        self._store: dict[str, deque[Candle]] = {}

    def append(self, timeframe: str, candle: Candle) -> None:
        series = self._store.setdefault(timeframe, deque(maxlen=self.limit))
        series.append(candle)

    def extend(self, timeframe: str, candles: Iterable[Candle]) -> None:
        for candle in candles:
            self.append(timeframe, candle)

    def series(self, timeframe: str) -> tuple[Candle, ...]:
        return tuple(self._store.get(timeframe, ()))

    def latest(self, timeframe: str) -> Candle | None:
        series = self._store.get(timeframe)
        if not series:
            return None
        return series[-1]

