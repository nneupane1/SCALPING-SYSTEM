from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from backend.app.data.downloader import MarketDataDownloader


class DownloaderTests(unittest.TestCase):
    def test_klines_to_df_filters_still_forming_candles(self) -> None:
        raw = [
            [1704067200000, "100", "101", "99", "100.5", "12", 1704067259999, "0", "0", "0", "0", "0"],
            [1704067260000, "100.5", "102", "100", "101.5", "18", 1704067319999, "0", "0", "0", "0", "0"],
            [1704067320000, "101.5", "103", "101", "102.2", "9", 9999999999999, "0", "0", "0", "0", "0"],
        ]

        df = MarketDataDownloader.klines_to_df(raw, closed_only=True, now_ms=1704067325000)

        self.assertEqual(2, len(df))
        self.assertEqual(["open", "high", "low", "close", "volume"], list(df.columns))
        self.assertAlmostEqual(101.5, float(df["close"].iloc[-1]))

    def test_read_ohlcv_csv_tolerates_extra_runtime_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime.csv"
            path.write_text(
                "\n".join(
                    [
                        "timestamp,open,high,low,close,volume",
                        "2026-05-24 11:29:00,77265.99,77289.97,77265.98,77286.48,3.71662",
                        "2026-05-24 11:30:00,77286.48,77289.44,77286.48,77289.43,1.0982,282",
                    ]
                ),
                encoding="utf-8",
            )

            df = MarketDataDownloader._read_ohlcv_csv(path)

            self.assertEqual(2, len(df))
            self.assertEqual(["timestamp", "open", "high", "low", "close", "volume"], list(df.columns))
            self.assertAlmostEqual(77289.43, float(df["close"].iloc[-1]))

    def test_read_ohlcv_csv_drops_malformed_timestamp_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.csv"
            path.write_text(
                "\n".join(
                    [
                        "timestamp,open,high,low,close,volume",
                        "2018-01-01 00:00:00,100,101,99,100.5,12",
                        "0.02,40.22949",
                        "2018-01-01 00:01:00,100.5,102,100,101.5,18",
                    ]
                ),
                encoding="utf-8",
            )

            df = MarketDataDownloader._read_ohlcv_csv(path)

            self.assertEqual(2, len(df))
            self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["timestamp"]))

    def test_read_ohlcv_csv_forces_timestamp_dtype_after_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.csv"
            path.write_text(
                "\n".join(
                    [
                        "timestamp,open,high,low,close,volume",
                        "2018-01-01 00:00:00,100,101,99,100.5,12",
                        "2018-01-01 00:01:00,100.5,102,100,101.5,18",
                    ]
                ),
                encoding="utf-8",
            )

            df = MarketDataDownloader._read_ohlcv_csv(path)

            self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["timestamp"]))
            self.assertEqual(pd.Timestamp("2018-01-01 00:00:00"), df["timestamp"].iloc[0])

    def test_repair_missing_intervals_backfills_missing_minute(self) -> None:
        downloader = MarketDataDownloader(config=Mock(), client=Mock(), progress_callback=None)
        downloader.config.system.binance.historical_limit = 1000
        downloader.config.system.binance.closed_klines_only = True
        downloader.client.get_klines.return_value = [
            [1704067260000, "100.5", "102", "100", "101.5", "18", 1704067319999, "0", "0", "0", "0", "0"],
        ]

        index = pd.to_datetime(
            [
                "2024-01-01 00:00:00",
                "2024-01-01 00:02:00",
            ]
        )
        df = pd.DataFrame(
            {
                "open": [100.0, 101.5],
                "high": [101.0, 103.0],
                "low": [99.0, 101.0],
                "close": [100.5, 102.2],
                "volume": [12.0, 9.0],
            },
            index=index,
        )

        repaired = downloader._repair_missing_intervals(
            df,
            symbol="BTCUSDT",
            interval="1m",
            start_bound=pd.Timestamp("2024-01-01 00:00:00"),
            end_bound=pd.Timestamp("2024-01-01 00:03:00"),
        )

        self.assertEqual(3, len(repaired))
        self.assertIn(pd.Timestamp("2024-01-01 00:01:00"), repaired.index)


if __name__ == "__main__":
    unittest.main()
