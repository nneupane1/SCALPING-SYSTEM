from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.app.backtest.runner import BacktestRunner
from backend.app.config.models import ConfigBundle, RiskConfig, StrategyConfig, SystemConfig
from backend.app.data import TimeframeBuilder, dataframe_to_candles


class BacktestGapAwarenessTests(unittest.TestCase):
    def test_gap_policy_blocks_pre_gap_and_post_gap_execution_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _build_config(root=Path(temp_dir) / "data_storage")
            runner = BacktestRunner(config)

            index = pd.to_datetime(
                [
                    "2026-01-01 10:00:00",
                    "2026-01-01 10:01:00",
                    "2026-01-01 10:02:00",
                    "2026-01-01 10:03:00",
                    "2026-01-01 10:04:00",
                    "2026-01-01 10:10:00",
                    "2026-01-01 10:11:00",
                    "2026-01-01 10:12:00",
                    "2026-01-01 10:13:00",
                    "2026-01-01 10:14:00",
                ]
            )
            df = pd.DataFrame(
                {
                    "open": [100, 101, 102, 103, 104, 110, 111, 112, 113, 114],
                    "high": [101, 102, 103, 104, 105, 111, 112, 113, 114, 115],
                    "low": [99, 100, 101, 102, 103, 109, 110, 111, 112, 113],
                    "close": [100.5, 101.5, 102.5, 103.5, 104.5, 110.5, 111.5, 112.5, 113.5, 114.5],
                    "volume": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
                },
                index=index,
            )

            frames = TimeframeBuilder(config).build_timeframes(df)
            execution_series = dataframe_to_candles(
                frames["5m"],
                symbol="BTCUSDT",
                timeframe="5m",
                index_is_close_time=True,
            )

            windows, policies = runner._build_gap_policy(
                symbol="BTCUSDT",
                df_1m=df,
                execution_series=execution_series,
                execution_timeframe="5m",
            )

            self.assertEqual(1, len(windows))
            window = windows[0]
            self.assertEqual(5, window.missing_minutes)
            self.assertEqual(0, window.previous_execution_index)
            self.assertEqual(1, window.next_execution_index)
            self.assertTrue(window.force_flat_before_gap)
            self.assertEqual(2, len(policies))
            self.assertEqual(("pre_gap",), policies[0].phases)
            self.assertTrue(policies[0].force_flat)
            self.assertEqual(("post_gap",), policies[1].phases)
            self.assertFalse(policies[1].force_flat)


def _build_config(*, root: Path) -> ConfigBundle:
    return ConfigBundle(
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
                "storage": {"root": str(root), "cache_limit": 100},
                "resample": {"closed": "left", "label": "right", "drop_incomplete": True},
                "backtest": {
                    "enabled": True,
                    "checkpoint_dir": "_checkpoints",
                    "checkpoint_suffix": ".checkpoint.json",
                    "save_every_steps": 10,
                    "output_dir": "backtest/output",
                    "resume_enabled": True,
                    "gap_aware": True,
                    "force_flat_before_gap": True,
                    "post_gap_cooldown_bars": 1,
                    "output_gap_windows": True,
                },
                "replay": {"enabled": True},
                "paper": {"enabled": True},
                "live": {"enabled": True},
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


if __name__ == "__main__":
    unittest.main()
