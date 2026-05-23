"""Execution-specific models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from backend.app.core.models import Side


class OrderType(str, Enum):
    """Supported order types for the current scaffold."""

    MARKET = "market"


@dataclass(frozen=True)
class OrderRequest:
    """A concrete order request to the broker layer."""

    order_id: str
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType
    submitted_at: datetime
    price_reference: float
    reason: str


@dataclass(frozen=True)
class FillReport:
    """Result of a submitted order."""

    order_id: str
    symbol: str
    side: Side
    quantity: float
    average_price: float
    filled_at: datetime
    simulated: bool

