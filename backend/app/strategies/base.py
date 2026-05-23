"""Strategy interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.core.models import MarketSnapshot, ScannerDecision, TradeSignal


class BaseStrategy(ABC):
    """Abstract contract for signal generation."""

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot, scanner_decision: ScannerDecision) -> TradeSignal | None:
        raise NotImplementedError

