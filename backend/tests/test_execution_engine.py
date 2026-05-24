from __future__ import annotations

import unittest

from backend.app.core.models import RiskPlan, Side, TradeSignal
from backend.app.execution.broker_base import PaperBroker
from backend.app.execution.execution_engine import ExecutionEngine
from backend.app.execution.order_manager import OrderManager
from backend.tests.helpers import make_candle


class ExecutionEngineTests(unittest.TestCase):
    def test_simulated_entry_uses_signal_generated_time(self) -> None:
        generated_at = make_candle(
            minute_offset=0,
            open_price=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10.0,
            timeframe="5m",
        ).close_time
        signal = TradeSignal(
            strategy_name="pullback_scalp",
            symbol="BTCUSDT",
            timeframe="5m",
            side=Side.LONG,
            generated_at=generated_at,
            entry_price=108.0,
            stop_price=105.0,
            first_target_price=111.0,
            confidence=0.75,
            reasons=("test",),
        )
        risk_plan = RiskPlan(
            equity=25_000.0,
            risk_fraction=0.005,
            risk_amount=125.0,
            risk_per_unit=3.0,
            position_size=41.6666666667,
            first_partial_at_price=111.0,
            first_partial_fraction=0.5,
            breakeven_after_partial=True,
        )

        order_manager = OrderManager(mode="backtest")
        engine = ExecutionEngine(order_manager=order_manager, broker=PaperBroker(order_manager))

        position = engine.execute_signal(signal, risk_plan)

        self.assertEqual(generated_at, position.opened_at)


if __name__ == "__main__":
    unittest.main()
