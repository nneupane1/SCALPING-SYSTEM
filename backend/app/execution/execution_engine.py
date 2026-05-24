"""Execution engine for opening and managing positions."""

from __future__ import annotations

from datetime import datetime
from math import isfinite

from backend.app.core.models import ClosedTrade, ManagementAction, ManagementDecision, OpenPosition, RiskPlan, TradeSignal

from .broker_base import Broker
from .models import OrderType
from .order_manager import OrderManager


class ExecutionEngine:
    """Translate signals and management actions into fills."""

    def __init__(self, order_manager: OrderManager, broker: Broker, *, max_slippage_bps: float = 0.0) -> None:
        self.order_manager = order_manager
        self.broker = broker
        self.max_slippage_bps = max_slippage_bps

    def execute_signal(self, signal: TradeSignal, risk_plan: RiskPlan) -> OpenPosition:
        request = self.order_manager.new_order_request(
            symbol=signal.symbol,
            side=signal.side,
            quantity=risk_plan.position_size,
            price_reference=signal.entry_price,
            reason="strategy_entry",
        )
        fill = self.broker.submit_order(request)
        allowed_slippage_bps = float(signal.metadata.get("max_slippage_bps", self.max_slippage_bps))
        if allowed_slippage_bps > 0:
            fill_slippage_bps = abs(fill.average_price - signal.entry_price) / signal.entry_price * 10_000
            if isfinite(fill_slippage_bps) and fill_slippage_bps > allowed_slippage_bps:
                raise ValueError(
                    f"Execution slippage {fill_slippage_bps:.2f} bps exceeds allowed buffer {allowed_slippage_bps:.2f} bps."
                )
        opened_at = signal.generated_at if fill.simulated else fill.filled_at
        position = OpenPosition(
            broker_metadata=self._build_entry_broker_metadata(fill),
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            side=signal.side,
            opened_at=opened_at,
            entry_price=fill.average_price,
            stop_price=signal.stop_price,
            initial_stop_price=signal.stop_price,
            initial_quantity=fill.quantity,
            remaining_quantity=fill.quantity,
            risk_plan=risk_plan,
            source_signal=signal,
        )
        if self.broker.supports_resting_orders():
            try:
                self._upsert_protective_stop(position)
            except Exception as exc:
                if self.broker.is_live():
                    try:
                        self._execute_reduce_only_order(
                            position=position,
                            quantity=position.remaining_quantity,
                            price_reference=position.entry_price,
                            reason="emergency_flatten_after_stop_failure",
                        )
                    except Exception as flatten_exc:
                        raise RuntimeError(
                            "Protective stop placement failed and emergency flatten also failed. "
                            "Manual intervention is required immediately."
                        ) from flatten_exc
                    raise RuntimeError(
                        "Protective stop placement failed after live entry. "
                        "A best-effort emergency flatten order was submitted."
                    ) from exc
                raise
        return position

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
            if self.broker.supports_resting_orders():
                self._upsert_protective_stop(position)
            return None
        if decision.action is ManagementAction.TAKE_PARTIAL:
            if decision.price is None or decision.quantity is None:
                raise ValueError("TAKE_PARTIAL decision requires both price and quantity.")
            quantity = min(decision.quantity, position.remaining_quantity)
            fill_price = decision.price
            if self.broker.is_live():
                fill = self._execute_reduce_only_order(
                    position=position,
                    quantity=quantity,
                    price_reference=decision.price,
                    reason=decision.reason,
                )
                quantity = min(fill.executed_quantity or fill.quantity, position.remaining_quantity)
                fill_price = fill.average_price
            pnl = self._pnl(
                side=position.side,
                entry_price=position.entry_price,
                exit_price=fill_price,
                quantity=quantity,
            )
            position.realized_pnl += pnl
            position.remaining_quantity -= quantity
            position.first_partial_taken = True
            position.first_partial_fill_price = fill_price
            if position.first_target_hit_after_bars is None:
                position.first_target_hit_after_bars = max(1, position.bars_held)
            if self.broker.supports_resting_orders():
                if position.remaining_quantity > 0:
                    self._upsert_protective_stop(position)
                else:
                    self._cancel_protective_stop(position)
            return None
        if decision.action is ManagementAction.EXIT:
            if decision.price is None:
                raise ValueError("EXIT decision requires an exit price.")
            exit_price = decision.price
            exit_quantity = position.remaining_quantity
            if self.broker.supports_resting_orders():
                self._cancel_protective_stop(position)
            if self.broker.is_live():
                fill = self._execute_reduce_only_order(
                    position=position,
                    quantity=position.remaining_quantity,
                    price_reference=decision.price,
                    reason=decision.reason,
                )
                exit_quantity = min(fill.executed_quantity or fill.quantity, position.remaining_quantity)
                exit_price = fill.average_price
            final_pnl = self._pnl(
                side=position.side,
                entry_price=position.entry_price,
                exit_price=exit_price,
                quantity=exit_quantity,
            )
            if exit_quantity < position.remaining_quantity:
                position.realized_pnl += final_pnl
                position.remaining_quantity -= exit_quantity
                if self.broker.supports_resting_orders() and position.remaining_quantity > 0:
                    self._upsert_protective_stop(position)
                return None
            total_realized_pnl = position.realized_pnl + final_pnl
            total_r = total_realized_pnl / position.initial_risk_amount if position.initial_risk_amount else 0.0
            metadata = dict(position.source_signal.metadata)
            metadata.update(
                {
                    "bars_held": position.bars_held,
                    "best_r_multiple": position.best_r_multiple,
                    "worst_r_multiple": position.worst_r_multiple,
                    "first_target_hit_after_bars": position.first_target_hit_after_bars,
                    "follow_through_state": position.follow_through_state,
                    "broker_metadata": dict(position.broker_metadata),
                }
            )
            closed_trade = ClosedTrade(
                symbol=position.symbol,
                timeframe=position.timeframe,
                side=position.side,
                opened_at=position.opened_at,
                closed_at=occurred_at,
                entry_price=position.entry_price,
                exit_price=exit_price,
                initial_quantity=position.initial_quantity,
                realized_pnl=total_realized_pnl,
                realized_r=total_r,
                reason=decision.reason,
                notes=tuple(position.source_signal.reasons),
                tags=self._build_trade_tags(position=position, reason=decision.reason, realized_r=total_r),
                metadata=metadata,
            )
            position.remaining_quantity = 0.0
            position.closed_at = occurred_at
            position.closed_reason = decision.reason
            return closed_trade
        raise ValueError(f"Unsupported management action: {decision.action}")

    def _pnl(self, *, side, entry_price: float, exit_price: float, quantity: float) -> float:
        direction = side.multiplier
        return (exit_price - entry_price) * direction * quantity

    def _build_entry_broker_metadata(self, fill) -> dict[str, object]:
        return {
            "entry_exchange_order_id": fill.exchange_order_id,
            "entry_status": fill.status.value,
            "entry_executed_quantity": fill.executed_quantity or fill.quantity,
        }

    def _execute_reduce_only_order(
        self,
        *,
        position: OpenPosition,
        quantity: float,
        price_reference: float,
        reason: str,
    ):
        request = self.order_manager.new_order_request(
            symbol=position.symbol,
            side=position.side,
            quantity=quantity,
            price_reference=price_reference,
            reason=reason,
            order_type=OrderType.MARKET,
            reduce_only=True,
        )
        fill = self.broker.submit_order(request)
        if (fill.executed_quantity or fill.quantity) <= 0:
            raise RuntimeError(f"Reduce-only order returned no fill for {position.symbol}.")
        return fill

    def _upsert_protective_stop(self, position: OpenPosition) -> None:
        if not self.broker.supports_resting_orders():
            return
        if position.side.value != "long":
            return
        self._cancel_protective_stop(position)
        if position.remaining_quantity <= 0:
            return
        stop_request = self.order_manager.new_order_request(
            symbol=position.symbol,
            side=position.side,
            quantity=position.remaining_quantity,
            price_reference=position.stop_price,
            reason="protective_stop",
            order_type=OrderType.STOP_LOSS,
            stop_price=position.stop_price,
            reduce_only=True,
            metadata={"protective_stop": True},
        )
        fill = self.broker.submit_order(stop_request)
        position.broker_metadata["protective_stop_client_order_id"] = stop_request.order_id
        position.broker_metadata["protective_stop_exchange_order_id"] = fill.exchange_order_id
        position.broker_metadata["protective_stop_status"] = fill.status.value

    def _cancel_protective_stop(self, position: OpenPosition) -> None:
        if not self.broker.supports_resting_orders():
            return
        client_order_id = position.broker_metadata.get("protective_stop_client_order_id")
        if not client_order_id:
            return
        exchange_order_id = position.broker_metadata.get("protective_stop_exchange_order_id")
        try:
            self.broker.cancel_order(
                symbol=position.symbol,
                client_order_id=str(client_order_id),
                exchange_order_id=None if exchange_order_id is None else int(exchange_order_id),
            )
        except Exception:
            pass
        position.broker_metadata.pop("protective_stop_client_order_id", None)
        position.broker_metadata.pop("protective_stop_exchange_order_id", None)
        position.broker_metadata.pop("protective_stop_status", None)

    def _build_trade_tags(
        self,
        *,
        position: OpenPosition,
        reason: str,
        realized_r: float,
    ) -> tuple[str, ...]:
        tags = [
            f"market_state:{position.source_signal.metadata.get('market_state', 'unknown')}",
            f"context:{position.source_signal.metadata.get('context_alignment', 'unknown')}",
            f"session:{position.source_signal.metadata.get('session_phase', 'unknown')}",
            f"quality:{position.source_signal.metadata.get('setup_quality_label', 'unknown')}",
        ]
        if realized_r >= 2.0:
            tags.append("outcome:runner_expansion")
        elif reason.startswith("early failure"):
            tags.append("outcome:loss_compression")
        elif realized_r <= 0 and position.best_r_multiple < 0.25:
            tags.append("outcome:fake_breakout")
        elif realized_r > 0:
            tags.append("outcome:clean_continuation")
        else:
            tags.append("outcome:standard_loss")
        return tuple(tags)
