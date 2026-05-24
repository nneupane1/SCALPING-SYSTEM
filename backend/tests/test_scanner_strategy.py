from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.app.config.models import (
    ScannerConfig,
    SessionWindow,
    SessionsConfig,
    StrategyFilterConfig,
    StrategyRuleConfig,
    StrategyTriggerConfig,
)
from backend.app.core.models import MarketSnapshot, ScannerState, Side
from backend.app.scanner.momentum_scanner import MomentumScanner
from backend.app.strategies.pullback_scalp import PullbackScalpStrategy

from backend.tests.helpers import make_candle


class ScannerAndStrategyTests(unittest.TestCase):
    def test_scanner_and_strategy_emit_long_signal_with_aligned_context(self) -> None:
        execution_candles = (
            make_candle(minute_offset=0, open_price=100.0, high=101.0, low=99.7, close=100.7, volume=10.0, timeframe="5m"),
            make_candle(minute_offset=5, open_price=100.7, high=101.4, low=100.5, close=101.1, volume=10.0, timeframe="5m"),
            make_candle(minute_offset=10, open_price=101.1, high=106.5, low=100.9, close=106.0, volume=28.0, timeframe="5m"),
            make_candle(minute_offset=15, open_price=106.0, high=106.1, low=104.8, close=105.2, volume=12.0, timeframe="5m"),
            make_candle(minute_offset=20, open_price=105.2, high=108.2, low=105.0, close=107.9, volume=24.0, timeframe="5m"),
        )
        context_candles = (
            make_candle(minute_offset=0, open_price=99.5, high=101.0, low=99.0, close=100.8, volume=18.0, timeframe="15m"),
            make_candle(minute_offset=15, open_price=100.8, high=102.1, low=100.4, close=101.8, volume=19.0, timeframe="15m"),
            make_candle(minute_offset=30, open_price=101.8, high=103.4, low=101.5, close=103.0, volume=21.0, timeframe="15m"),
            make_candle(minute_offset=45, open_price=103.0, high=104.6, low=102.7, close=104.1, volume=23.0, timeframe="15m"),
        )
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            generated_at=execution_candles[-1].close_time,
            candles={"5m": execution_candles, "15m": context_candles},
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
            execution_timeframe="5m",
        )
        strategy = PullbackScalpStrategy(
            strategy_config=StrategyRuleConfig(name="pullback_scalp", allow_long=True, allow_short=True),
            filter_config=StrategyFilterConfig.from_mapping(
                {
                    "context": {
                        "enabled": True,
                        "timeframe": "15m",
                        "lookback_bars": 4,
                        "aligned_risk_multiplier": 1.0,
                        "neutral_risk_multiplier": 0.9,
                        "conflicting_risk_multiplier": 0.75,
                    },
                    "market_state": {"enabled": False},
                    "quality": {"enabled": False},
                    "session": {"enabled": False},
                }
            ),
            trigger_config=StrategyTriggerConfig(
                require_breakout_close=True,
                min_close_position=0.7,
                min_body_ratio=1.2,
                stop_buffer_ratio=0.05,
            ),
            execution_timeframe="5m",
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
        self.assertEqual("aligned", signal.metadata["context_alignment"])
        self.assertEqual(1.0, signal.metadata["risk_fraction_multiplier"])

    def test_strategy_reduces_risk_when_context_conflicts(self) -> None:
        execution_candles = (
            make_candle(minute_offset=0, open_price=100.0, high=101.0, low=99.7, close=100.7, volume=10.0, timeframe="5m"),
            make_candle(minute_offset=5, open_price=100.7, high=101.4, low=100.5, close=101.1, volume=10.0, timeframe="5m"),
            make_candle(minute_offset=10, open_price=101.1, high=106.5, low=100.9, close=106.0, volume=28.0, timeframe="5m"),
            make_candle(minute_offset=15, open_price=106.0, high=106.1, low=104.8, close=105.2, volume=12.0, timeframe="5m"),
            make_candle(minute_offset=20, open_price=105.2, high=108.2, low=105.0, close=107.9, volume=24.0, timeframe="5m"),
        )
        context_candles = (
            make_candle(minute_offset=0, open_price=110.0, high=110.4, low=108.9, close=109.1, volume=18.0, timeframe="15m"),
            make_candle(minute_offset=15, open_price=109.1, high=109.3, low=107.8, close=108.2, volume=19.0, timeframe="15m"),
            make_candle(minute_offset=30, open_price=108.2, high=108.4, low=106.7, close=107.1, volume=21.0, timeframe="15m"),
            make_candle(minute_offset=45, open_price=107.1, high=107.2, low=105.5, close=105.9, volume=23.0, timeframe="15m"),
        )
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            generated_at=execution_candles[-1].close_time,
            candles={"5m": execution_candles, "15m": context_candles},
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
            execution_timeframe="5m",
        )
        strategy = PullbackScalpStrategy(
            strategy_config=StrategyRuleConfig(name="pullback_scalp", allow_long=True, allow_short=True),
            filter_config=StrategyFilterConfig.from_mapping(
                {
                    "context": {
                        "enabled": True,
                        "timeframe": "15m",
                        "lookback_bars": 4,
                        "aligned_risk_multiplier": 1.0,
                        "neutral_risk_multiplier": 0.9,
                        "conflicting_risk_multiplier": 0.75,
                    },
                    "market_state": {"enabled": False},
                    "quality": {"enabled": False},
                    "session": {"enabled": False},
                }
            ),
            trigger_config=StrategyTriggerConfig(
                require_breakout_close=True,
                min_close_position=0.7,
                min_body_ratio=1.2,
                stop_buffer_ratio=0.05,
            ),
            execution_timeframe="5m",
        )

        decision = scanner.scan(snapshot)
        signal = strategy.evaluate(snapshot, decision)

        self.assertEqual(ScannerState.READY, decision.state)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual("conflicting", signal.metadata["context_alignment"])
        self.assertEqual(0.75, signal.metadata["risk_fraction_multiplier"])
        self.assertLess(signal.confidence, 0.9)

    def test_strategy_blocks_outside_active_sessions(self) -> None:
        execution_candles = (
            make_candle(minute_offset=0, open_price=100.0, high=101.0, low=99.7, close=100.7, volume=10.0, timeframe="5m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
            make_candle(minute_offset=5, open_price=100.7, high=101.4, low=100.5, close=101.1, volume=10.0, timeframe="5m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
            make_candle(minute_offset=10, open_price=101.1, high=106.5, low=100.9, close=106.0, volume=28.0, timeframe="5m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
            make_candle(minute_offset=15, open_price=106.0, high=106.1, low=104.8, close=105.2, volume=12.0, timeframe="5m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
            make_candle(minute_offset=20, open_price=105.2, high=108.2, low=105.0, close=107.9, volume=24.0, timeframe="5m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
        )
        context_candles = (
            make_candle(minute_offset=0, open_price=99.5, high=101.0, low=99.0, close=100.8, volume=18.0, timeframe="15m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
            make_candle(minute_offset=15, open_price=100.8, high=102.1, low=100.4, close=101.8, volume=19.0, timeframe="15m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
            make_candle(minute_offset=30, open_price=101.8, high=103.4, low=101.5, close=103.0, volume=21.0, timeframe="15m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
            make_candle(minute_offset=45, open_price=103.0, high=104.6, low=102.7, close=104.1, volume=23.0, timeframe="15m", base_time=datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)),
        )
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            generated_at=execution_candles[-1].close_time,
            candles={"5m": execution_candles, "15m": context_candles},
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
            execution_timeframe="5m",
        )
        strategy = PullbackScalpStrategy(
            strategy_config=StrategyRuleConfig(name="pullback_scalp", allow_long=True, allow_short=True),
            filter_config=StrategyFilterConfig.from_mapping(
                {
                    "context": {"enabled": False},
                    "market_state": {"enabled": False},
                    "quality": {"enabled": False},
                    "session": {"enabled": True, "block_outside_sessions": True},
                }
            ),
            trigger_config=StrategyTriggerConfig(
                require_breakout_close=True,
                min_close_position=0.7,
                min_body_ratio=1.2,
                stop_buffer_ratio=0.05,
            ),
            execution_timeframe="5m",
            sessions_config=SessionsConfig(
                enabled=True,
                timezone="Europe/Berlin",
                active_windows=(SessionWindow(name="london", start="08:00", end="11:00"),),
            ),
        )

        decision = scanner.scan(snapshot)
        signal = strategy.evaluate(snapshot, decision)

        self.assertEqual(ScannerState.READY, decision.state)
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()
