"""Order identity and simulated-fill helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import count

from backend.app.core.models import Side

from .models import FillReport, OrderRequest, OrderType


class OrderManager:
    """Manage order IDs and deterministic paper fills."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self._sequence = count(1)

    def new_order_request(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: float,
        price_reference: float,
        reason: str,
    ) -> OrderRequest:
        order_id = f"{self.mode}-{next(self._sequence):06d}"
        return OrderRequest(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            submitted_at=datetime.now(timezone.utc),
            price_reference=price_reference,
            reason=reason,
        )

    def simulate_fill(self, request: OrderRequest, fill_price: float) -> FillReport:
        return FillReport(
            order_id=request.order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            average_price=fill_price,
            filled_at=datetime.now(timezone.utc),
            simulated=True,
        )

