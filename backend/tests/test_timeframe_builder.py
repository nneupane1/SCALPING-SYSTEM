from __future__ import annotations

import unittest

import pandas as pd

from backend.app.config.models import ConfigBundle, RiskConfig, StrategyConfig, SystemConfig
from backend.app.data.timeframe_builder import TimeframeBuilder


class TimeframeBuilderTests(unittest.TestCase):
    def test_builder_resamples_and_drops_incomplete_higher_timeframe(self) -> None:
        config = ConfigBundle(
            system=SystemConfig.from_mapping(
                {
                    "app": {"name": "test", "mode": "paper", "debug": False},
                    "account": {"initial_equity": 1000},
                    "market": {
                        "symbol": "BTCUSDT",
                        "base_timeframe": "1m",
                        "execution_timeframe": "5m",
                        "context_timeframes": ["15m"],
                        "supported_execution_timeframes": ["5m", "15m"],
                    },
                    "sessions": {"enabled": True, "timezone": "UTC", "active_windows": []},
                    "storage": {"root": "data_storage", "cache_limit": 100},
                    "resample": {"closed": "left", "label": "right", "drop_incomplete": True},
                    "transport": {"websocket_broadcast_buffer": 10},
                }
            ),
            strategy=StrategyConfig.from_mapping(
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
                    "strategy": {"name": "pullback_scalp", "allow_long": True, "allow_short": True},
                }
            ),
            risk=RiskConfig.from_mapping(
                {
                    "risk": {"risk_per_trade": 0.01},
                    "management": {},
                    "execution": {},
                }
            ),
        )

        index = pd.date_range("2026-01-01 10:00:00", periods=6, freq="1min")
        df = pd.DataFrame(
            {
                "open": [100, 101, 102, 103, 104, 105],
                "high": [101, 102, 103, 104, 105, 106],
                "low": [99, 100, 101, 102, 103, 104],
                "close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
                "volume": [10, 11, 12, 13, 14, 15],
            },
            index=index,
        )

        frames = TimeframeBuilder(config).build_timeframes(df)

        self.assertIn("5m", frames)
        self.assertEqual(1, len(frames["5m"]))
        self.assertEqual(100, int(frames["5m"]["open"].iloc[0]))


if __name__ == "__main__":
    unittest.main()
