from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()

