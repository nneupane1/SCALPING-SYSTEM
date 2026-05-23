"""Broker interfaces and a paper broker implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import FillReport, OrderRequest
from .order_manager import OrderManager


class Broker(ABC):
    """Abstract broker contract."""

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> FillReport:
        raise NotImplementedError


class PaperBroker(Broker):
    """Immediate-fill paper broker used in replay and paper mode."""

    def __init__(self, order_manager: OrderManager) -> None:
        self.order_manager = order_manager

    def submit_order(self, request: OrderRequest) -> FillReport:
        return self.order_manager.simulate_fill(request=request, fill_price=request.price_reference)

