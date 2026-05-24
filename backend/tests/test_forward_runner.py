from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.app.config.models import ConfigBundle, RiskConfig, StrategyConfig, SystemConfig
from backend.app.data.timeframe_builder import TimeframeBuilder
from backend.app.live import ForwardRunner


class _FakeDownloader:
    def __init__(self, root: Path, symbol: str, bootstrap_df: pd.DataFrame, recent_df: pd.DataFrame) -> None:
        self.root = root
        self.symbol = symbol
        self.bootstrap_df = bootstrap_df
        self.recent_df = recent_df

    def load_from_csv(self, filepath) -> pd.DataFrame:
        return self.bootstrap_df.copy()

    def fetch_recent(self, **kwargs) -> pd.DataFrame:
        return self.recent_df.copy()

    def realtime_runtime_path(self, *, symbol: str, interval: str | None = None) -> Path:
        base_interval = interval or "1m"
        return self.root / "data_storage" / symbol / base_interval / f"{symbol}_{base_interval}_live_runtime.csv"

    def latest_timestamp_in_csv(self, path) -> pd.Timestamp | None:
        csv_path = Path(path)
        if not csv_path.exists():
            return None
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        if df.empty:
            return None
        return pd.Timestamp(df["timestamp"].iloc[-1])

    def append_realtime_history(
        self,
        *,
        symbol: str,
        frame: pd.DataFrame,
        interval: str | None = None,
        last_persisted_at: pd.Timestamp | None = None,
    ) -> pd.Timestamp | None:
        path = self.realtime_runtime_path(symbol=symbol, interval=interval)
        path.parent.mkdir(parents=True, exist_ok=True)
        append_df = frame if last_persisted_at is None else frame.loc[frame.index > last_persisted_at]
        if append_df.empty:
            return last_persisted_at
        append_df.to_csv(path, mode="a", header=not path.exists())
        return append_df.index.max()


class ForwardRunnerTests(unittest.TestCase):
    def test_forward_runner_bootstraps_and_writes_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            symbol = "BTCUSDT"
            history_path = root / "data_storage" / symbol / "1m" / f"{symbol}_1m_2024-01-01_to_2024-01-02.csv"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")

            bootstrap_index = pd.date_range("2024-01-01 10:00:00", periods=10, freq="1min")
            recent_index = pd.date_range("2024-01-01 10:10:00", periods=5, freq="1min")
            bootstrap_df = pd.DataFrame(
                {
                    "open": [100 + i for i in range(10)],
                    "high": [100.4 + i for i in range(10)],
                    "low": [99.6 + i for i in range(10)],
                    "close": [100.2 + i for i in range(10)],
                    "volume": [10 + i for i in range(10)],
                },
                index=bootstrap_index,
            )
            recent_df = pd.DataFrame(
                {
                    "open": [110 + i for i in range(5)],
                    "high": [110.4 + i for i in range(5)],
                    "low": [109.6 + i for i in range(5)],
                    "close": [110.2 + i for i in range(5)],
                    "volume": [20 + i for i in range(5)],
                },
                index=recent_index,
            )

            config = ConfigBundle(
                system=SystemConfig.from_mapping(
                    {
                        "app": {"name": "test", "mode": "paper", "debug": False},
                        "account": {"initial_equity": 20_000},
                        "market": {
                            "symbol": symbol,
                            "base_timeframe": "1m",
                            "execution_timeframe": "5m",
                            "context_timeframes": ["15m"],
                            "supported_execution_timeframes": ["5m", "15m"],
                        },
                        "sessions": {"enabled": True, "timezone": "UTC", "active_windows": []},
                        "storage": {"root": str(root / "data_storage"), "cache_limit": 1000},
                        "paper": {
                            "output_dir": str(root / "paper_output"),
                            "poll_seconds": 0,
                            "recent_limit": 100,
                            "warmup_base_candles": 100,
                            "save_every_polls": 1,
                            "resume_enabled": True,
                        },
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
                            "max_pullback_bars": 2,
                            "compression_lookback": 5,
                        },
                        "strategy": {
                            "name": "pullback_scalp",
                            "allow_long": True,
                            "allow_short": True,
                        },
                        "filters": {
                            "context": {
                                "enabled": True,
                                "timeframe": "15m",
                                "lookback_bars": 4,
                            }
                        },
                    }
                ),
                risk=RiskConfig.from_mapping(
                    {
                        "risk": {"risk_per_trade": 0.005},
                        "management": {},
                        "execution": {},
                    }
                ),
            )

            downloader = _FakeDownloader(root, symbol, bootstrap_df, recent_df)
            runner = ForwardRunner(
                config,
                mode="paper",
                downloader=downloader,
                timeframe_builder=TimeframeBuilder(config),
            )
            summary = runner.run(symbol=symbol, max_polls=1)

            self.assertEqual(1, summary.polls_processed)
            self.assertEqual(1, summary.snapshots_processed)
            self.assertIsNotNone(summary.latest_execution_close)
            self.assertTrue(summary.checkpoint_path.exists())
            self.assertTrue(downloader.realtime_runtime_path(symbol=symbol).exists())

    def test_forward_runner_ignores_incompatible_checkpoint_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            symbol = "BTCUSDT"
            history_path = root / "data_storage" / symbol / "1m" / f"{symbol}_1m_2024-01-01_to_2024-01-02.csv"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")

            bootstrap_index = pd.date_range("2024-01-01 10:00:00", periods=10, freq="1min")
            recent_index = pd.date_range("2024-01-01 10:10:00", periods=5, freq="1min")
            bootstrap_df = pd.DataFrame(
                {
                    "open": [100 + i for i in range(10)],
                    "high": [100.4 + i for i in range(10)],
                    "low": [99.6 + i for i in range(10)],
                    "close": [100.2 + i for i in range(10)],
                    "volume": [10 + i for i in range(10)],
                },
                index=bootstrap_index,
            )
            recent_df = pd.DataFrame(
                {
                    "open": [110 + i for i in range(5)],
                    "high": [110.4 + i for i in range(5)],
                    "low": [109.6 + i for i in range(5)],
                    "close": [110.2 + i for i in range(5)],
                    "volume": [20 + i for i in range(5)],
                },
                index=recent_index,
            )

            config = ConfigBundle(
                system=SystemConfig.from_mapping(
                    {
                        "app": {"name": "test", "mode": "paper", "debug": False},
                        "account": {"initial_equity": 25_000},
                        "market": {
                            "symbol": symbol,
                            "base_timeframe": "1m",
                            "execution_timeframe": "5m",
                            "context_timeframes": ["15m"],
                            "supported_execution_timeframes": ["5m", "15m"],
                        },
                        "sessions": {"enabled": True, "timezone": "UTC", "active_windows": []},
                        "storage": {"root": str(root / "data_storage"), "cache_limit": 1000},
                        "paper": {
                            "output_dir": str(root / "paper_output"),
                            "poll_seconds": 0,
                            "recent_limit": 100,
                            "warmup_base_candles": 100,
                            "save_every_polls": 1,
                            "resume_enabled": True,
                        },
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
                            "max_pullback_bars": 2,
                            "compression_lookback": 5,
                        },
                        "strategy": {
                            "name": "pullback_scalp",
                            "allow_long": True,
                            "allow_short": True,
                        },
                    }
                ),
                risk=RiskConfig.from_mapping(
                    {
                        "risk": {"risk_per_trade": 0.005},
                        "management": {},
                        "execution": {},
                    }
                ),
            )

            checkpoint_path = (
                Path(config.system.paper.output_dir)
                / config.system.paper.checkpoint_dir
                / f"{symbol}_5m_paper{config.system.paper.checkpoint_suffix}"
            )
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(
                """
{
  "mode": "paper",
  "symbol": "BTCUSDT",
  "execution_timeframe": "5m",
  "latest_execution_close": "2024-01-01T10:15:00",
  "portfolio": {
    "current_equity": 20000,
    "realized_pnl": 0.0,
    "peak_equity": 20000,
    "win_count": 0,
    "loss_count": 0,
    "closed_trades": [],
    "active_position": null
  }
}
                """.strip(),
                encoding="utf-8",
            )

            runner = ForwardRunner(
                config,
                mode="paper",
                downloader=_FakeDownloader(root, symbol, bootstrap_df, recent_df),
                timeframe_builder=TimeframeBuilder(config),
            )
            summary = runner.run(symbol=symbol, max_polls=1)

            self.assertEqual(25_000, summary.current_equity)


if __name__ == "__main__":
    unittest.main()
