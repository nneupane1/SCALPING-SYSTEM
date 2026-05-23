"""Risk sizing rules."""

from __future__ import annotations

from backend.app.config.models import RiskConfig
from backend.app.core.models import RiskPlan, TradeSignal


class RiskManager:
    """Convert a valid signal into sized exposure."""

    def __init__(self, risk_config: RiskConfig) -> None:
        self.risk_config = risk_config

    def build_plan(self, signal: TradeSignal, equity: float) -> RiskPlan:
        risk_per_unit = signal.risk_per_unit
        if risk_per_unit <= 0:
            raise ValueError("Signal risk per unit must be positive.")

        stop_distance_ratio = risk_per_unit / signal.entry_price
        if stop_distance_ratio < self.risk_config.risk.min_stop_distance_ratio:
            raise ValueError("Stop distance is unrealistically tight for configured limits.")

        risk_amount = equity * self.risk_config.risk.risk_per_trade
        position_size = risk_amount / risk_per_unit

        max_notional = self.risk_config.risk.max_position_notional
        if max_notional is not None:
            capped_size = max_notional / signal.entry_price
            position_size = min(position_size, capped_size)

        if position_size <= 0:
            raise ValueError("Position size resolved to zero.")

        first_partial_at_price = signal.entry_price + (
            self.risk_config.management.first_partial_at_r
            * risk_per_unit
            * signal.side.multiplier
        )
        return RiskPlan(
            equity=equity,
            risk_fraction=self.risk_config.risk.risk_per_trade,
            risk_amount=risk_amount,
            risk_per_unit=risk_per_unit,
            position_size=position_size,
            first_partial_at_price=first_partial_at_price,
            first_partial_fraction=self.risk_config.management.first_partial_size,
            breakeven_after_partial=self.risk_config.management.move_stop_to_breakeven_after_first_partial,
        )

