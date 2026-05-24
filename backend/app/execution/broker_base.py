"""Broker interfaces and a paper broker implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from .models import BrokerOrderState, FillReport, OrderRequest
from .order_manager import OrderManager


class Broker(ABC):
    """Abstract broker contract."""

    def is_live(self) -> bool:
        return False

    def supports_resting_orders(self) -> bool:
        return False

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> FillReport:
        raise NotImplementedError

    def cancel_order(self, *, symbol: str, client_order_id: str, exchange_order_id: int | None = None) -> BrokerOrderState | None:
        raise NotImplementedError

    def fetch_order(self, *, symbol: str, client_order_id: str | None = None, exchange_order_id: int | None = None) -> BrokerOrderState | None:
        raise NotImplementedError

    def fetch_open_orders(self, *, symbol: str | None = None) -> tuple[BrokerOrderState, ...]:
        raise NotImplementedError


class PaperBroker(Broker):
    """Immediate-fill paper broker used in replay and paper mode."""

    def __init__(self, order_manager: OrderManager) -> None:
        self.order_manager = order_manager

    def submit_order(self, request: OrderRequest) -> FillReport:
        return self.order_manager.simulate_fill(request=request, fill_price=request.price_reference)

    def cancel_order(self, *, symbol: str, client_order_id: str, exchange_order_id: int | None = None) -> BrokerOrderState | None:
        state = self.order_manager.state_by_client_id(client_order_id)
        if state is None:
            return None
        self.order_manager.register_cancellation(
            client_order_id,
            exchange_order_id=exchange_order_id,
            occurred_at=datetime.now(timezone.utc),
        )
        return self.order_manager.state_by_client_id(client_order_id)

    def fetch_order(self, *, symbol: str, client_order_id: str | None = None, exchange_order_id: int | None = None) -> BrokerOrderState | None:
        if client_order_id is not None:
            return self.order_manager.state_by_client_id(client_order_id)
        if exchange_order_id is not None:
            return self.order_manager.state_by_exchange_id(exchange_order_id)
        return None

    def fetch_open_orders(self, *, symbol: str | None = None) -> tuple[BrokerOrderState, ...]:
        return self.order_manager.active_states(symbol=symbol)
