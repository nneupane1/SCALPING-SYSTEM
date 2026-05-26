from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from backend.app.data.downloader import MarketDataDownloader


class DownloaderTests(unittest.TestCase):
    def _config_for_tempdir(self, tmpdir: str) -> SimpleNamespace:
        return SimpleNamespace(
            system=SimpleNamespace(
                storage=SimpleNamespace(root=Path(tmpdir)),
                market=SimpleNamespace(symbol="BTCUSDT", base_timeframe="1m"),
                history=SimpleNamespace(
                    start_date="2018-01-01 00:00:00",
                    end_date="2026-05-23 00:00:00",
                ),
                downloads=SimpleNamespace(
                    history=SimpleNamespace(
                        checkpoint_dir="_checkpoints",
                        checkpoint_suffix=".checkpoint.json",
                        partial_suffix=".partial.csv",
                        resume_enabled=True,
                        cleanup_partial_on_complete=True,
                        save_every_batches=10,
                        status_every_batches=10,
                    )
                ),
                binance=SimpleNamespace(
                    historical_limit=1000,
                    closed_klines_only=True,
                    throttle_seconds=0,
                    default_interval="1m",
                ),
            )
        )

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

    def test_fetch_full_history_reuses_covering_completed_csv_without_redownloading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config_for_tempdir(tmpdir)
            client = Mock()
            downloader = MarketDataDownloader(config=config, client=client, progress_callback=None)
            client.describe_verify_mode.return_value = "enabled"

            folder = Path(tmpdir) / "BTCUSDT" / "1m"
            folder.mkdir(parents=True, exist_ok=True)
            source_path = folder / "BTCUSDT_1m_2018-01-01T00.00.00_to_2026-05-23T00.00.00.csv"
            index = pd.to_datetime(
                [
                    "2020-10-15 02:59:00",
                    "2020-10-15 03:00:00",
                    "2020-10-15 03:01:00",
                    "2026-05-22 23:59:00",
                ]
            )
            source_df = pd.DataFrame(
                {
                    "open": [1.0, 2.0, 3.0, 4.0],
                    "high": [1.1, 2.1, 3.1, 4.1],
                    "low": [0.9, 1.9, 2.9, 3.9],
                    "close": [1.05, 2.05, 3.05, 4.05],
                    "volume": [10.0, 20.0, 30.0, 40.0],
                },
                index=index,
            )
            source_df.to_csv(source_path, index_label="timestamp")

            df = downloader.fetch_full_history(
                symbol="BTCUSDT",
                interval="1m",
                start_date="2020-10-15 03:00:00",
                end_date="2026-05-23 00:00:00",
            )

            expected_path = folder / "BTCUSDT_1m_2020-10-15T03.00.00_to_2026-05-23T00.00.00.csv"
            expected_checkpoint = (
                folder
                / "_checkpoints"
                / "BTCUSDT_1m_2020-10-15T03.00.00_to_2026-05-23T00.00.00.csv.checkpoint.json"
            )
            self.assertTrue(expected_path.exists())
            self.assertTrue(expected_checkpoint.exists())
            self.assertEqual(
                [pd.Timestamp("2020-10-15 03:00:00"), pd.Timestamp("2020-10-15 03:01:00"), pd.Timestamp("2026-05-22 23:59:00")],
                list(df.index),
            )
            client.get_klines.assert_not_called()


if __name__ == "__main__":
    unittest.main()
