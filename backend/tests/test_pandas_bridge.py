from __future__ import annotations

import unittest
from datetime import datetime, timezone

import pandas as pd

from backend.app.data.pandas_bridge import dataframe_to_candles


class PandasBridgeTests(unittest.TestCase):
    def test_right_labeled_resampled_index_is_treated_as_close_time(self) -> None:
        frame = pd.DataFrame(
            {
                "open": [100.0],
                "high": [105.0],
                "low": [99.5],
                "close": [104.5],
                "volume": [60.0],
            },
            index=[pd.Timestamp("2026-01-01 10:05:00")],
        )

        candle = dataframe_to_candles(
            frame,
            symbol="BTCUSDT",
            timeframe="5m",
            index_is_close_time=True,
        )[0]

        self.assertEqual(datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc), candle.open_time)
        self.assertEqual(datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc), candle.close_time)


if __name__ == "__main__":
    unittest.main()
