"""Order identity and broker-state reconciliation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import count
from threading import Condition

from backend.app.core.models import Side

from .models import (
    BrokerOrderState,
    ExecutionReportEvent,
    FillReport,
    OrderRequest,
    OrderStatus,
    OrderType,
    TimeInForce,
)


class OrderManager:
    """Manage local order identities and broker-side order states."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self._sequence = count(1)
        self._states_by_client_id: dict[str, BrokerOrderState] = {}
        self._states_by_exchange_id: dict[int, BrokerOrderState] = {}
        self._condition = Condition()

    def new_order_request(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: float,
        price_reference: float,
        reason: str,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: TimeInForce | None = None,
        reduce_only: bool = False,
        recv_window: float | None = None,
        test_only: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> OrderRequest:
        timestamp = datetime.now(timezone.utc)
        order_id = f"{self.mode}-{timestamp.strftime('%Y%m%d%H%M%S')}-{next(self._sequence):06d}"
        request = OrderRequest(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            submitted_at=timestamp,
            price_reference=price_reference,
            reason=reason,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            recv_window=recv_window,
            test_only=test_only,
            metadata={} if metadata is None else dict(metadata),
        )
        self._register_request(request)
        return request

    def _register_request(self, request: OrderRequest) -> None:
        with self._condition:
            self._states_by_client_id[request.order_id] = BrokerOrderState(
                client_order_id=request.order_id,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                requested_quantity=request.quantity,
                status=OrderStatus.NEW,
                created_at=request.submitted_at,
                updated_at=request.submitted_at,
            )
            self._condition.notify_all()

    def register_submission_result(self, request: OrderRequest, fill: FillReport) -> None:
        with self._condition:
            state = self._states_by_client_id.get(request.order_id)
            if state is None:
                state = BrokerOrderState(
                    client_order_id=request.order_id,
                    symbol=request.symbol,
                    side=request.side,
                    order_type=request.order_type,
                    requested_quantity=request.quantity,
                    status=fill.status,
                )
                self._states_by_client_id[request.order_id] = state
            state.exchange_order_id = fill.exchange_order_id
            state.status = fill.status
            state.filled_quantity = fill.executed_quantity if fill.executed_quantity is not None else fill.quantity
            state.average_price = fill.average_price
            state.last_price = fill.average_price
            state.updated_at = fill.filled_at
            if fill.exchange_order_id is not None:
                self._states_by_exchange_id[fill.exchange_order_id] = state
            self._condition.notify_all()

    def reconcile_execution_report(self, event: ExecutionReportEvent) -> BrokerOrderState:
        with self._condition:
            state = self._states_by_client_id.get(event.client_order_id)
            if state is None:
                state = BrokerOrderState(
                    client_order_id=event.client_order_id,
                    symbol=event.symbol,
                    side=event.side,
                    order_type=event.order_type,
                    requested_quantity=max(event.cumulative_filled_quantity, event.last_executed_quantity),
                    status=event.status,
                    created_at=event.transaction_time,
                )
                self._states_by_client_id[event.client_order_id] = state
            state.exchange_order_id = event.exchange_order_id
            state.status = event.status
            state.filled_quantity = event.cumulative_filled_quantity
            state.cumulative_quote_quantity = event.cumulative_quote_quantity
            state.last_price = event.last_executed_price
            if event.cumulative_filled_quantity > 0:
                state.average_price = (
                    event.cumulative_quote_quantity / event.cumulative_filled_quantity
                    if event.cumulative_filled_quantity > 0
                    else state.average_price
                )
            state.rejection_reason = event.rejection_reason
            state.updated_at = event.transaction_time
            self._states_by_exchange_id[event.exchange_order_id] = state
            self._condition.notify_all()
            return state

    def register_cancellation(self, client_order_id: str, *, exchange_order_id: int | None, occurred_at: datetime) -> None:
        with self._condition:
            state = self._states_by_client_id.get(client_order_id)
            if state is not None:
                state.status = OrderStatus.CANCELED
                state.updated_at = occurred_at
                if exchange_order_id is not None:
                    state.exchange_order_id = exchange_order_id
                    self._states_by_exchange_id[exchange_order_id] = state
            self._condition.notify_all()

    def wait_for_terminal_state(self, client_order_id: str, timeout_seconds: float) -> BrokerOrderState | None:
        end_time = datetime.now(timezone.utc).timestamp() + timeout_seconds
        with self._condition:
            while True:
                state = self._states_by_client_id.get(client_order_id)
                if state is not None and state.status.is_terminal:
                    return state
                remaining = end_time - datetime.now(timezone.utc).timestamp()
                if remaining <= 0:
                    return state
                self._condition.wait(timeout=remaining)

    def state_by_client_id(self, client_order_id: str) -> BrokerOrderState | None:
        with self._condition:
            return self._states_by_client_id.get(client_order_id)

    def state_by_exchange_id(self, exchange_order_id: int) -> BrokerOrderState | None:
        with self._condition:
            return self._states_by_exchange_id.get(exchange_order_id)

    def active_states(self, *, symbol: str | None = None) -> tuple[BrokerOrderState, ...]:
        with self._condition:
            rows = []
            for state in self._states_by_client_id.values():
                if not state.is_active:
                    continue
                if symbol is not None and state.symbol != symbol:
                    continue
                rows.append(state)
            return tuple(rows)

    def simulate_fill(self, request: OrderRequest, fill_price: float) -> FillReport:
        report = FillReport(
            order_id=request.order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            average_price=fill_price,
            filled_at=datetime.now(timezone.utc),
            simulated=True,
            status=OrderStatus.FILLED,
            executed_quantity=request.quantity,
        )
        self.register_submission_result(request, report)
        return report
