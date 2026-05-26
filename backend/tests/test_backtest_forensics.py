from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.app.backtest.csv_logger import DailySummaryCsvLogger
from backend.app.core.models import ClosedTrade, Side


class BacktestForensicsTests(unittest.TestCase):
    def test_daily_summary_logger_aggregates_trades_by_local_day(self) -> None:
        trades = [
            ClosedTrade(
                symbol="BTCUSDT",
                timeframe="5m",
                side=Side.LONG,
                opened_at=datetime(2026, 1, 5, 7, 0, tzinfo=timezone.utc),
                closed_at=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc),
                entry_price=100.0,
                exit_price=101.0,
                initial_quantity=1.0,
                realized_pnl=120.0,
                realized_r=1.2,
                reason="test",
            ),
            ClosedTrade(
                symbol="BTCUSDT",
                timeframe="5m",
                side=Side.SHORT,
                opened_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
                closed_at=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
                entry_price=101.0,
                exit_price=102.0,
                initial_quantity=1.0,
                realized_pnl=-60.0,
                realized_r=-0.6,
                reason="test",
            ),
            ClosedTrade(
                symbol="BTCUSDT",
                timeframe="5m",
                side=Side.LONG,
                opened_at=datetime(2026, 1, 6, 7, 0, tzinfo=timezone.utc),
                closed_at=datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc),
                entry_price=102.0,
                exit_price=104.0,
                initial_quantity=1.0,
                realized_pnl=180.0,
                realized_r=1.5,
                reason="test",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily_summary.csv"
            rows = DailySummaryCsvLogger(path).write_all(
                trades,
                timezone_name="Europe/Berlin",
                starting_equity=25_000.0,
                good_day_threshold_r=1.0,
            )

            self.assertEqual(2, len(rows))
            self.assertEqual("2026-01-05", rows[0]["date_local"])
            self.assertEqual(2, rows[0]["closed_trades"])
            self.assertAlmostEqual(0.6, float(rows[0]["realized_r"]))
            self.assertFalse(bool(rows[0]["good_day_target_hit"]))
            self.assertEqual("2026-01-06", rows[1]["date_local"])
            self.assertEqual(1, rows[1]["closed_trades"])
            self.assertTrue(bool(rows[1]["good_day_target_hit"]))

            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                written = list(reader)

            self.assertEqual(2, len(written))
            self.assertEqual("2026-01-05", written[0]["date_local"])
            self.assertEqual("2", written[0]["closed_trades"])


if __name__ == "__main__":
    unittest.main()
