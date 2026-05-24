"""Execution-specific models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from backend.app.core.models import Side


class OrderType(str, Enum):
    """Supported order types for the current broker integration."""

    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    """Supported time-in-force values."""

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(str, Enum):
    """Broker-side order status."""

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    PENDING_CANCEL = "PENDING_CANCEL"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }


class ExecutionType(str, Enum):
    """Execution type from Binance execution reports."""

    NEW = "NEW"
    CANCELED = "CANCELED"
    REPLACED = "REPLACED"
    REJECTED = "REJECTED"
    TRADE = "TRADE"
    EXPIRED = "EXPIRED"
    TRADE_PREVENTION = "TRADE_PREVENTION"


@dataclass(frozen=True)
class OrderFill:
    """A single trade fill attached to an order response."""

    price: float
    quantity: float
    commission: float
    commission_asset: str | None
    trade_id: int | None


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
    price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce | None = None
    reduce_only: bool = False
    recv_window: float | None = None
    test_only: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


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
    exchange_order_id: int | None = None
    status: OrderStatus = OrderStatus.FILLED
    executed_quantity: float | None = None
    fills: tuple[OrderFill, ...] = ()


@dataclass
class BrokerOrderState:
    """Mutable broker-side view of one order lifecycle."""

    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    requested_quantity: float
    status: OrderStatus
    exchange_order_id: int | None = None
    filled_quantity: float = 0.0
    cumulative_quote_quantity: float = 0.0
    average_price: float = 0.0
    last_price: float = 0.0
    rejection_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.requested_quantity - self.filled_quantity)

    @property
    def is_active(self) -> bool:
        return not self.status.is_terminal


@dataclass(frozen=True)
class BalanceUpdate:
    """Private account balance update from user stream."""

    asset: str
    free: float
    locked: float
    updated_at: datetime


@dataclass(frozen=True)
class ExecutionReportEvent:
    """Normalized execution report from Binance user-data stream."""

    client_order_id: str
    exchange_order_id: int
    symbol: str
    side: Side
    order_type: OrderType
    execution_type: ExecutionType
    status: OrderStatus
    last_executed_quantity: float
    cumulative_filled_quantity: float
    last_executed_price: float
    cumulative_quote_quantity: float
    transaction_time: datetime
    rejection_reason: str | None

