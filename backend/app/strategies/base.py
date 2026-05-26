"""Strategy interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from backend.app.core.models import MarketSnapshot, ScannerDecision, TradeSignal

if TYPE_CHECKING:
    from backend.app.data.models import Candle


class BaseStrategy(ABC):
    """Abstract contract for signal generation."""

    @abstractmethod
    def evaluate(
        self,
        snapshot: MarketSnapshot,
        scanner_decision: ScannerDecision,
        *,
        current_trigger_candle: "Candle | None" = None,
    ) -> TradeSignal | None:
        raise NotImplementedError
