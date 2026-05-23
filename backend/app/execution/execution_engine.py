"""Execution engine for opening and managing positions."""

from __future__ import annotations

from datetime import datetime

from backend.app.core.models import ClosedTrade, ManagementAction, ManagementDecision, OpenPosition, RiskPlan, TradeSignal

from .broker_base import Broker
from .order_manager import OrderManager


class ExecutionEngine:
    """Translate signals and management actions into fills."""

    def __init__(self, order_manager: OrderManager, broker: Broker) -> None:
        self.order_manager = order_manager
        self.broker = broker

    def execute_signal(self, signal: TradeSignal, risk_plan: RiskPlan) -> OpenPosition:
        request = self.order_manager.new_order_request(
            symbol=signal.symbol,
            side=signal.side,
            quantity=risk_plan.position_size,
            price_reference=signal.entry_price,
            reason="strategy_entry",
        )
        fill = self.broker.submit_order(request)
        return OpenPosition(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            side=signal.side,
            opened_at=fill.filled_at,
            entry_price=fill.average_price,
            stop_price=signal.stop_price,
            initial_stop_price=signal.stop_price,
            initial_quantity=fill.quantity,
            remaining_quantity=fill.quantity,
            risk_plan=risk_plan,
            source_signal=signal,
        )

    def apply_management(
        self,
        *,
        position: OpenPosition,
        decision: ManagementDecision,
        occurred_at: datetime,
    ) -> ClosedTrade | None:
        if decision.action is ManagementAction.HOLD:
            return None
        if decision.action is ManagementAction.MOVE_STOP:
            if decision.price is None:
                raise ValueError("MOVE_STOP decision requires a price.")
            position.stop_price = decision.price
            return None
        if decision.action is ManagementAction.TAKE_PARTIAL:
            if decision.price is None or decision.quantity is None:
                raise ValueError("TAKE_PARTIAL decision requires both price and quantity.")
            quantity = min(decision.quantity, position.remaining_quantity)
            pnl = self._pnl(
                side=position.side,
                entry_price=position.entry_price,
                exit_price=decision.price,
                quantity=quantity,
            )
            position.realized_pnl += pnl
            position.remaining_quantity -= quantity
            position.first_partial_taken = True
            position.first_partial_fill_price = decision.price
            return None
        if decision.action is ManagementAction.EXIT:
            if decision.price is None:
                raise ValueError("EXIT decision requires an exit price.")
            final_pnl = self._pnl(
                side=position.side,
                entry_price=position.entry_price,
                exit_price=decision.price,
                quantity=position.remaining_quantity,
            )
            total_realized_pnl = position.realized_pnl + final_pnl
            total_r = total_realized_pnl / position.initial_risk_amount if position.initial_risk_amount else 0.0
            closed_trade = ClosedTrade(
                symbol=position.symbol,
                timeframe=position.timeframe,
                side=position.side,
                opened_at=position.opened_at,
                closed_at=occurred_at,
                entry_price=position.entry_price,
                exit_price=decision.price,
                initial_quantity=position.initial_quantity,
                realized_pnl=total_realized_pnl,
                realized_r=total_r,
                reason=decision.reason,
                notes=tuple(position.source_signal.reasons),
            )
            position.remaining_quantity = 0.0
            position.closed_at = occurred_at
            position.closed_reason = decision.reason
            return closed_trade
        raise ValueError(f"Unsupported management action: {decision.action}")

    def _pnl(self, *, side, entry_price: float, exit_price: float, quantity: float) -> float:
        direction = side.multiplier
        return (exit_price - entry_price) * direction * quantity

