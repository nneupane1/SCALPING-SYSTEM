from __future__ import annotations

import unittest

from backend.app.config.models import ScannerConfig, StrategyRuleConfig, StrategyTriggerConfig
from backend.app.core.models import MarketSnapshot, ScannerState, Side
from backend.app.scanner.momentum_scanner import MomentumScanner
from backend.app.strategies.pullback_scalp import PullbackScalpStrategy

from backend.tests.helpers import make_candle


class ScannerAndStrategyTests(unittest.TestCase):
    def test_scanner_and_strategy_emit_long_signal(self) -> None:
        candles = (
            make_candle(minute_offset=0, open_price=100.0, high=101.0, low=99.7, close=100.7, volume=10.0),
            make_candle(minute_offset=15, open_price=100.7, high=101.4, low=100.5, close=101.1, volume=10.0),
            make_candle(minute_offset=30, open_price=101.1, high=106.5, low=100.9, close=106.0, volume=28.0),
            make_candle(minute_offset=45, open_price=106.0, high=106.1, low=104.8, close=105.2, volume=12.0),
            make_candle(minute_offset=60, open_price=105.2, high=108.2, low=105.0, close=107.9, volume=24.0),
        )
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            generated_at=candles[-1].close_time,
            candles={"15m": candles},
        )
        scanner = MomentumScanner(
            scanner_config=ScannerConfig(
                min_impulse_body_ratio=1.5,
                min_volume_ratio=1.2,
                max_pullback_depth_ratio=0.8,
                max_pullback_body_ratio=0.75,
                min_pullback_bars=1,
                max_pullback_bars=1,
                compression_lookback=2,
            ),
            execution_timeframe="15m",
        )
        strategy = PullbackScalpStrategy(
            strategy_config=StrategyRuleConfig(name="pullback_scalp", allow_long=True, allow_short=True),
            trigger_config=StrategyTriggerConfig(
                require_breakout_close=True,
                min_close_position=0.7,
                min_body_ratio=1.2,
                stop_buffer_ratio=0.05,
            ),
            execution_timeframe="15m",
        )

        decision = scanner.scan(snapshot)
        signal = strategy.evaluate(snapshot, decision)

        self.assertEqual(ScannerState.READY, decision.state)
        self.assertEqual(Side.LONG, decision.side)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertGreater(signal.entry_price, float(decision.trigger_level))
        self.assertLess(signal.stop_price, float(decision.invalidation_level))


if __name__ == "__main__":
    unittest.main()
