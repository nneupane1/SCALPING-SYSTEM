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


if __name__ == "__main__":
    unittest.main()
