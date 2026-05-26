from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.app.backtest import BacktestRunner
from backend.app.config.models import ConfigBundle, RiskConfig, StrategyConfig, SystemConfig
from backend.app.data.timeframe_builder import TimeframeBuilder


class _StaticHistoryDownloader:
    def __init__(self, frames_by_symbol: dict[str, pd.DataFrame]) -> None:
        self.frames_by_symbol = {
            symbol: frame.copy()
            for symbol, frame in frames_by_symbol.items()
        }

    def fetch_full_history(self, *, symbol: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.frames_by_symbol[symbol].copy()


class MultiSymbolBacktestTests(unittest.TestCase):
    def test_runner_processes_watchlist_scope_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _build_config(root=root)
            index = pd.date_range("2024-01-01 08:00:00", periods=20, freq="1min")
            frames_by_symbol = {
                "BTCUSDT": _build_frame(index=index, base_price=40_000.0),
                "ETHUSDT": _build_frame(index=index, base_price=2_000.0),
            }
            runner = BacktestRunner(
                config,
                downloader=_StaticHistoryDownloader(frames_by_symbol),
                timeframe_builder=TimeframeBuilder(config),
            )

            summary = runner.run(
                symbols=("BTCUSDT", "ETHUSDT"),
                start_date="2024-01-01 08:00:00",
                end_date="2024-01-01 08:20:00",
            )

            self.assertEqual("BTCUSDT__ETHUSDT", summary.symbol)
            self.assertEqual(8, summary.steps_processed)
            self.assertTrue((root / "backtest_output" / "equity.csv").exists())
            self.assertTrue((root / "backtest_output" / "trades.csv").exists())
            self.assertTrue((root / "backtest_output" / "diagnostics.json").exists())
            self.assertTrue(
                (
                    root
                    / "backtest_output"
                    / "_checkpoints"
                    / "BTCUSDT__ETHUSDT_5m_2024-01-01T08.00.00_to_2024-01-01T08.20.00.checkpoint.json"
                ).exists()
            )


def _build_frame(*, index: pd.DatetimeIndex, base_price: float) -> pd.DataFrame:
    values = [base_price + (step * 3.0) for step in range(len(index))]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 2.0 for value in values],
            "low": [value - 2.0 for value in values],
            "close": [value + 1.0 for value in values],
            "volume": [100 + step for step in range(len(index))],
        },
        index=index,
    )


def _build_config(*, root: Path) -> ConfigBundle:
    return ConfigBundle(
        system=SystemConfig.from_mapping(
            {
                "app": {"name": "test", "mode": "backtest", "debug": False},
                "account": {"initial_equity": 25_000, "base_currency": "EUR"},
                "market": {
                    "symbol": "BTCUSDT",
                    "watchlist_symbols": ["ETHUSDT"],
                    "base_timeframe": "1m",
                    "execution_timeframe": "5m",
                    "context_timeframes": ["15m"],
                    "supported_execution_timeframes": ["5m", "15m"],
                },
                "sessions": {"enabled": False, "timezone": "UTC", "active_windows": []},
                "storage": {"root": str(root / "data_storage"), "cache_limit": 1000},
                "resample": {"closed": "left", "label": "right", "drop_incomplete": True},
                "history": {
                    "start_date": "2024-01-01 08:00:00",
                    "end_date": "2024-01-01 08:20:00",
                },
                "backtest": {
                    "enabled": True,
                    "checkpoint_dir": "_checkpoints",
                    "checkpoint_suffix": ".checkpoint.json",
                    "save_every_steps": 2,
                    "output_dir": str(root / "backtest_output"),
                    "resume_enabled": False,
                    "gap_aware": False,
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
                    "min_impulse_body_ratio": 3.0,
                    "min_volume_ratio": 3.0,
                    "min_impulse_range_ratio": 2.0,
                    "min_impulse_close_position": 0.95,
                    "min_impulse_efficiency": 0.9,
                    "max_pullback_depth_ratio": 0.2,
                    "max_pullback_body_ratio": 0.2,
                    "min_pullback_bars": 2,
                    "max_pullback_bars": 2,
                    "compression_lookback": 5,
                },
                "strategy": {"name": "pullback_scalp", "allow_long": True, "allow_short": True},
            }
        ),
        risk=RiskConfig.from_mapping(
            {
                "risk": {
                    "risk_per_trade": 0.005,
                    "max_open_positions": 2,
                    "max_total_open_risk_fraction": 0.01,
                    "max_positions_per_symbol": 1,
                },
                "management": {},
                "execution": {},
            }
        ),
    )


if __name__ == "__main__":
    unittest.main()
