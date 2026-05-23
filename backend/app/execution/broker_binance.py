"""Binance broker adapter placeholder."""

from __future__ import annotations

from .broker_base import Broker
from .models import FillReport, OrderRequest


class BinanceBroker(Broker):
    """Live broker adapter stub.

    This remains intentionally unimplemented until authenticated exchange
    integration, idempotency, and state reconciliation are designed properly.
    """

    def submit_order(self, request: OrderRequest) -> FillReport:
        raise NotImplementedError("Binance live order submission is not implemented yet.")

