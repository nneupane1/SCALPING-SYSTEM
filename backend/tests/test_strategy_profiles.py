from __future__ import annotations

import unittest

from backend.app.config.models import StrategyConfig


class StrategyProfileTests(unittest.TestCase):
    def test_profile_resolution_returns_timeframe_specific_expression(self) -> None:
        config = StrategyConfig.from_mapping(
            {
                "scanner": {
                    "min_impulse_body_ratio": 1.5,
                    "min_volume_ratio": 1.2,
                    "max_pullback_depth_ratio": 0.8,
                    "max_pullback_body_ratio": 0.75,
                    "min_pullback_bars": 1,
                    "max_pullback_bars": 3,
                    "compression_lookback": 5,
                },
                "strategy": {
                    "name": "pullback_scalp",
                    "allow_long": True,
                    "allow_short": True,
                    "trigger": {
                        "require_breakout_close": True,
                        "min_close_position": 0.7,
                        "min_body_ratio": 1.2,
                        "stop_buffer_ratio": 0.05,
                    },
                },
                "profiles": {
                    "5m": {
                        "execution_timeframe": "5m",
                        "scanner": {
                            "min_impulse_body_ratio": 1.35,
                            "min_volume_ratio": 1.15,
                            "max_pullback_depth_ratio": 0.75,
                            "max_pullback_body_ratio": 0.8,
                            "min_pullback_bars": 1,
                            "max_pullback_bars": 3,
                            "compression_lookback": 6,
                        },
                        "trigger": {
                            "timeframe": "1m",
                            "require_breakout_close": True,
                            "reference_lookback_bars": 6,
                            "min_close_position": 0.65,
                            "min_body_ratio": 1.15,
                            "stop_buffer_ratio": 0.04,
                        },
                        "cadence": {
                            "expected_trades_per_day_low": 8,
                            "expected_trades_per_day_high": 15,
                            "runner_emphasis": "secondary",
                        },
                    },
                    "15m": {
                        "execution_timeframe": "15m",
                        "scanner": {
                            "min_impulse_body_ratio": 1.6,
                            "min_volume_ratio": 1.25,
                            "max_pullback_depth_ratio": 0.85,
                            "max_pullback_body_ratio": 0.7,
                            "min_pullback_bars": 1,
                            "max_pullback_bars": 4,
                            "compression_lookback": 5,
                        },
                        "trigger": {
                            "timeframe": "5m",
                            "require_breakout_close": True,
                            "reference_lookback_bars": 5,
                            "min_close_position": 0.72,
                            "min_body_ratio": 1.25,
                            "stop_buffer_ratio": 0.05,
                        },
                        "cadence": {
                            "expected_trades_per_day_low": 2,
                            "expected_trades_per_day_high": 5,
                            "runner_emphasis": "primary",
                        },
                    },
                },
            }
        )

        rapid = config.resolve_profile("5m")
        slow = config.resolve_profile("15m")
        fallback = config.resolve_profile("30m")

        self.assertEqual("5m", rapid.execution_timeframe)
        self.assertEqual("1m", rapid.trigger_timeframe)
        self.assertEqual(8, rapid.cadence.expected_trades_per_day_low)
        self.assertEqual(1.35, rapid.scanner.min_impulse_body_ratio)
        self.assertEqual("secondary", rapid.cadence.runner_emphasis)

        self.assertEqual("15m", slow.execution_timeframe)
        self.assertEqual("5m", slow.trigger_timeframe)
        self.assertEqual(2, slow.cadence.expected_trades_per_day_low)
        self.assertEqual(1.6, slow.scanner.min_impulse_body_ratio)
        self.assertEqual("primary", slow.cadence.runner_emphasis)

        self.assertEqual("30m", fallback.execution_timeframe)
        self.assertEqual("30m", fallback.trigger_timeframe)
        self.assertEqual(1.5, fallback.scanner.min_impulse_body_ratio)
        self.assertEqual("balanced", fallback.cadence.runner_emphasis)


if __name__ == "__main__":
    unittest.main()
