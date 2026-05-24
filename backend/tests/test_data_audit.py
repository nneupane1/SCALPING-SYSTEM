from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.app.config.models import (
    ConfigBundle,
    RiskConfig,
    StrategyConfig,
    SystemConfig,
    history_path_label,
)
from backend.app.data import MarketDataAuditor, TimeframeBuilder


class DataAuditTests(unittest.TestCase):
    def test_audit_flags_missing_base_minute_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "data_storage"
            config = _build_config(root=root)
            symbol = config.system.market.symbol
            start_date = "2026-01-01 10:00:00"
            end_date = "2026-01-01 10:04:00"

            index = pd.to_datetime(
                [
                    "2026-01-01 10:00:00",
                    "2026-01-01 10:01:00",
                    "2026-01-01 10:03:00",
                    "2026-01-01 10:04:00",
                ]
            )
            frame = pd.DataFrame(
                {
                    "open": [100, 101, 103, 104],
                    "high": [101, 102, 104, 105],
                    "low": [99, 100, 102, 103],
                    "close": [100.5, 101.5, 103.5, 104.5],
                    "volume": [10, 11, 13, 14],
                },
                index=index,
            )
            _write_history_csv(
                root=root,
                symbol=symbol,
                timeframe="1m",
                start_date=start_date,
                end_date=end_date,
                frame=frame,
            )

            report = MarketDataAuditor(config).audit_history(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                include_derived=False,
            )

            self.assertFalse(report.ok)
            self.assertTrue(
                any(
                    issue.code == "bad_step_count" and issue.timeframe == "1m"
                    for issue in report.issues
                )
            )
            summary = next(summary for summary in report.summaries if summary.timeframe == "1m")
            self.assertEqual(1, summary.missing_intervals)

    def test_audit_flags_saved_derived_frame_that_diverges_from_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "data_storage"
            config = _build_config(root=root)
            symbol = config.system.market.symbol
            start_date = "2026-01-01 10:00:00"
            end_date = "2026-01-01 10:05:00"

            index = pd.date_range(start_date, periods=6, freq="1min")
            frame = pd.DataFrame(
                {
                    "open": [100, 101, 102, 103, 104, 105],
                    "high": [101, 102, 103, 104, 105, 106],
                    "low": [99, 100, 101, 102, 103, 104],
                    "close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
                    "volume": [10, 11, 12, 13, 14, 15],
                },
                index=index,
            )
            _write_history_csv(
                root=root,
                symbol=symbol,
                timeframe="1m",
                start_date=start_date,
                end_date=end_date,
                frame=frame,
            )
            TimeframeBuilder(config).build_timeframes_and_save(
                frame,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                base_path=root,
            )

            derived_path = (
                root
                / symbol
                / "5m"
                / f"{symbol}_5m_{history_path_label(start_date)}_to_{history_path_label(end_date)}.csv"
            )
            derived = pd.read_csv(derived_path, parse_dates=["timestamp"]).set_index("timestamp")
            derived.iloc[0, derived.columns.get_loc("open")] = float(derived.iloc[0]["open"]) + 1.0
            derived.to_csv(derived_path)

            report = MarketDataAuditor(config).audit_history(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                include_derived=True,
            )

            self.assertFalse(report.ok)
            self.assertTrue(
                any(
                    issue.code == "recomputed_mismatch" and issue.timeframe == "5m"
                    for issue in report.issues
                )
            )
            summary = next(summary for summary in report.summaries if summary.timeframe == "5m")
            self.assertFalse(summary.recomputed_match)
            self.assertGreater(summary.recomputed_value_mismatch_cells or 0, 0)


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
                    "context_timeframes": [],
                    "supported_execution_timeframes": ["5m"],
                },
                "sessions": {"enabled": True, "timezone": "UTC", "active_windows": []},
                "storage": {"root": str(root), "cache_limit": 100},
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


def _write_history_csv(
    *,
    root: Path,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    frame: pd.DataFrame,
) -> None:
    folder = root / symbol / timeframe
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{symbol}_{timeframe}_{history_path_label(start_date)}_to_{history_path_label(end_date)}.csv"
    frame.to_csv(path, index_label="timestamp")


if __name__ == "__main__":
    unittest.main()
