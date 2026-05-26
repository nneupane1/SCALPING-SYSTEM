from __future__ import annotations

import unittest

from backend.app.replay.multi_asset_replay import MultiAssetReplayEngine
from backend.tests.helpers import make_candle


class MultiAssetReplayEngineTests(unittest.TestCase):
    def test_step_batch_groups_same_timestamp_across_symbols(self) -> None:
        btc_5m = (
            make_candle(minute_offset=0, open_price=100.0, high=101.0, low=99.5, close=100.8, volume=10.0, timeframe="5m"),
            make_candle(minute_offset=5, open_price=100.8, high=102.0, low=100.4, close=101.7, volume=11.0, timeframe="5m"),
        )
        eth_5m = (
            make_candle(minute_offset=0, open_price=50.0, high=50.8, low=49.7, close=50.5, volume=8.0, timeframe="5m"),
            make_candle(minute_offset=5, open_price=50.5, high=51.6, low=50.2, close=51.3, volume=9.0, timeframe="5m"),
        )

        engine = MultiAssetReplayEngine(
            clock_timeframe="5m",
            execution_timeframe="5m",
            candles_by_symbol={
                "BTCUSDT": {"5m": btc_5m},
                "ETHUSDT": {"5m": eth_5m},
            },
        )

        first_batch = engine.step_batch()
        self.assertEqual(2, len(first_batch))
        self.assertEqual(("BTCUSDT", "ETHUSDT"), tuple(step.symbol for step in first_batch))
        self.assertEqual(0, first_batch[0].execution_index)
        self.assertEqual(0, first_batch[1].execution_index)
        self.assertEqual(2, engine.cursor.processed_steps)

        second_batch = engine.step_batch()
        self.assertEqual(2, len(second_batch))
        self.assertEqual(1, second_batch[0].execution_index)
        self.assertEqual(1, second_batch[1].execution_index)
        self.assertFalse(engine.has_next())

    def test_step_batch_uses_lower_clock_timeframe_without_lookahead(self) -> None:
        btc_5m = (
            make_candle(minute_offset=0, open_price=100.0, high=101.0, low=99.5, close=100.8, volume=10.0, timeframe="5m"),
        )
        btc_1m = (
            make_candle(minute_offset=0, open_price=100.0, high=100.3, low=99.9, close=100.2, volume=2.0, timeframe="1m"),
            make_candle(minute_offset=1, open_price=100.2, high=100.4, low=100.1, close=100.3, volume=2.0, timeframe="1m"),
            make_candle(minute_offset=2, open_price=100.3, high=100.5, low=100.2, close=100.4, volume=2.0, timeframe="1m"),
        )

        engine = MultiAssetReplayEngine(
            clock_timeframe="1m",
            execution_timeframe="5m",
            candles_by_symbol={
                "BTCUSDT": {"1m": btc_1m, "5m": btc_5m},
            },
        )

        first_batch = engine.step_batch()
        self.assertEqual(1, len(first_batch))
        self.assertEqual(0, first_batch[0].clock_index)
        self.assertIsNone(first_batch[0].execution_index)
        self.assertFalse(first_batch[0].execution_just_closed)
        self.assertEqual(btc_1m[0].close_time, first_batch[0].snapshot.generated_at)

        second_batch = engine.step_batch()
        self.assertEqual(1, len(second_batch))
        self.assertEqual(1, second_batch[0].clock_index)
        self.assertIsNone(second_batch[0].execution_index)
        self.assertFalse(second_batch[0].execution_just_closed)


if __name__ == "__main__":
    unittest.main()
