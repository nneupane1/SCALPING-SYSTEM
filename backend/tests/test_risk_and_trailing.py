from __future__ import annotations

import unittest

from backend.app.config.models import ExecutionConfig, ManagementConfig, RiskConfig, RiskLimitsConfig
from backend.app.core.models import ManagementAction, OpenPosition, RiskPlan, Side, TradeSignal
from backend.app.risk.risk_manager import RiskManager
from backend.app.risk.trailing_engine import TrailingEngine

from backend.tests.helpers import make_candle


class RiskAndTrailingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RiskConfig(
            risk=RiskLimitsConfig(
                risk_per_trade=0.005,
                max_open_positions=1,
                max_daily_loss_r=3.0,
                max_consecutive_losses=4,
                min_stop_distance_ratio=0.0005,
                max_position_notional=50_000,
            ),
            management=ManagementConfig(
                first_partial_at_r=1.0,
                first_partial_size=0.5,
                move_stop_to_breakeven_after_first_partial=True,
                trailing_mode="previous_candle_structure",
                trailing_lookback_bars=1,
            ),
            execution=ExecutionConfig(allow_live_orders=False, max_slippage_bps=5.0),
        )

    def test_risk_manager_builds_position_size(self) -> None:
        signal = TradeSignal(
            strategy_name="pullback_scalp",
            symbol="BTCUSDT",
            timeframe="15m",
            side=Side.LONG,
            generated_at=make_candle(
                minute_offset=0,
                open_price=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
            ).close_time,
            entry_price=108.0,
            stop_price=105.0,
            first_target_price=111.0,
            confidence=0.8,
            reasons=("test",),
        )

        plan = RiskManager(self.config).build_plan(signal=signal, equity=20_000.0)

        self.assertAlmostEqual(100.0, plan.risk_amount)
        self.assertAlmostEqual(3.0, plan.risk_per_unit)
        self.assertAlmostEqual(100.0 / 3.0, plan.position_size)
        self.assertAlmostEqual(111.0, plan.first_partial_at_price)

    def test_risk_manager_applies_signal_risk_multiplier(self) -> None:
        signal = TradeSignal(
            strategy_name="pullback_scalp",
            symbol="BTCUSDT",
            timeframe="5m",
            side=Side.LONG,
            generated_at=make_candle(
                minute_offset=0,
                open_price=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
            ).close_time,
            entry_price=108.0,
            stop_price=105.0,
            first_target_price=111.0,
            confidence=0.68,
            reasons=("test",),
            metadata={"risk_fraction_multiplier": 0.75},
        )

        plan = RiskManager(self.config).build_plan(signal=signal, equity=20_000.0)

        self.assertAlmostEqual(0.00375, plan.risk_fraction)
        self.assertAlmostEqual(75.0, plan.risk_amount)
        self.assertAlmostEqual(25.0, plan.position_size)

    def test_risk_manager_uses_actual_deployed_risk_after_notional_cap(self) -> None:
        signal = TradeSignal(
            strategy_name="pullback_scalp",
            symbol="BTCUSDT",
            timeframe="5m",
            side=Side.LONG,
            generated_at=make_candle(
                minute_offset=0,
                open_price=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
            ).close_time,
            entry_price=10_000.0,
            stop_price=9_995.0,
            first_target_price=10_005.0,
            confidence=0.7,
            reasons=("test",),
        )

        plan = RiskManager(self.config).build_plan(signal=signal, equity=20_000.0)

        self.assertAlmostEqual(5.0, plan.position_size)
        self.assertAlmostEqual(25.0, plan.risk_amount)
        self.assertAlmostEqual(0.00125, plan.risk_fraction)

    def test_trailing_engine_takes_partial_then_moves_to_breakeven(self) -> None:
        trailing = TrailingEngine(self.config)
        position = OpenPosition(
            symbol="BTCUSDT",
            timeframe="15m",
            side=Side.LONG,
            opened_at=make_candle(
                minute_offset=0,
                open_price=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
            ).close_time,
            entry_price=108.0,
            stop_price=105.0,
            initial_stop_price=105.0,
            initial_quantity=10.0,
            remaining_quantity=10.0,
            risk_plan=RiskPlan(
                equity=20_000.0,
                risk_fraction=0.005,
                risk_amount=100.0,
                risk_per_unit=3.0,
                position_size=10.0,
                first_partial_at_price=111.0,
                first_partial_fraction=0.5,
                breakeven_after_partial=True,
            ),
            source_signal=TradeSignal(
                strategy_name="pullback_scalp",
                symbol="BTCUSDT",
                timeframe="15m",
                side=Side.LONG,
                generated_at=make_candle(
                    minute_offset=0,
                    open_price=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    volume=10.0,
                ).close_time,
                entry_price=108.0,
                stop_price=105.0,
                first_target_price=111.0,
                confidence=0.8,
                reasons=("test",),
            ),
        )
        candles = (
            make_candle(minute_offset=0, open_price=108.0, high=109.0, low=107.5, close=108.5, volume=10.0),
            make_candle(minute_offset=15, open_price=108.5, high=111.2, low=108.2, close=110.8, volume=14.0),
        )

        decisions = trailing.evaluate(position=position, candles=candles)

        self.assertEqual(2, len(decisions))
        self.assertEqual(ManagementAction.TAKE_PARTIAL, decisions[0].action)
        self.assertEqual(5.0, decisions[0].quantity)
        self.assertEqual(ManagementAction.MOVE_STOP, decisions[1].action)
        self.assertEqual(108.0, decisions[1].price)

    def test_trailing_engine_compresses_loss_when_trade_never_proves_itself(self) -> None:
        trailing = TrailingEngine(self.config)
        position = OpenPosition(
            symbol="BTCUSDT",
            timeframe="5m",
            side=Side.LONG,
            opened_at=make_candle(
                minute_offset=0,
                open_price=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
                timeframe="5m",
            ).close_time,
            entry_price=108.0,
            stop_price=105.0,
            initial_stop_price=105.0,
            initial_quantity=10.0,
            remaining_quantity=10.0,
            risk_plan=RiskPlan(
                equity=20_000.0,
                risk_fraction=0.005,
                risk_amount=100.0,
                risk_per_unit=3.0,
                position_size=10.0,
                first_partial_at_price=111.0,
                first_partial_fraction=0.5,
                breakeven_after_partial=True,
            ),
            source_signal=TradeSignal(
                strategy_name="pullback_scalp",
                symbol="BTCUSDT",
                timeframe="5m",
                side=Side.LONG,
                generated_at=make_candle(
                    minute_offset=0,
                    open_price=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    volume=10.0,
                    timeframe="5m",
                ).close_time,
                entry_price=108.0,
                stop_price=105.0,
                first_target_price=111.0,
                confidence=0.8,
                reasons=("test",),
            ),
        )

        sequences = (
            (make_candle(minute_offset=0, open_price=108.0, high=108.2, low=107.3, close=107.8, volume=8.0, timeframe="5m"),),
            (
                make_candle(minute_offset=0, open_price=108.0, high=108.2, low=107.3, close=107.8, volume=8.0, timeframe="5m"),
                make_candle(minute_offset=5, open_price=107.8, high=108.1, low=107.1, close=107.4, volume=7.0, timeframe="5m"),
            ),
            (
                make_candle(minute_offset=0, open_price=108.0, high=108.2, low=107.3, close=107.8, volume=8.0, timeframe="5m"),
                make_candle(minute_offset=5, open_price=107.8, high=108.1, low=107.1, close=107.4, volume=7.0, timeframe="5m"),
                make_candle(minute_offset=10, open_price=107.4, high=107.7, low=106.8, close=106.9, volume=7.0, timeframe="5m"),
            ),
        )

        first = trailing.evaluate(position=position, candles=sequences[0])
        second = trailing.evaluate(position=position, candles=sequences[1])
        third = trailing.evaluate(position=position, candles=sequences[2])

        self.assertEqual((), first)
        self.assertEqual((), second)
        self.assertEqual(1, len(third))
        self.assertEqual(ManagementAction.EXIT, third[0].action)
        self.assertEqual("early failure exit due to missing follow-through", third[0].reason)


if __name__ == "__main__":
    unittest.main()
