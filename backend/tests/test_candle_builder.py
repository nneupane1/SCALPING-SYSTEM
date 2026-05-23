from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.app.data.candle_builder import CandleBuilder
from backend.app.data.models import Tick


class CandleBuilderTests(unittest.TestCase):
    def test_builder_closes_and_gap_fills_missing_minutes(self) -> None:
        builder = CandleBuilder(symbol="BTCUSDT")

        builder.update(
            Tick(
                symbol="BTCUSDT",
                price=100.0,
                quantity=1.0,
                event_time=datetime(2026, 1, 5, 10, 0, 10, tzinfo=timezone.utc),
            )
        )
        builder.update(
            Tick(
                symbol="BTCUSDT",
                price=101.0,
                quantity=2.0,
                event_time=datetime(2026, 1, 5, 10, 0, 40, tzinfo=timezone.utc),
            )
        )
        result = builder.update(
            Tick(
                symbol="BTCUSDT",
                price=102.0,
                quantity=1.0,
                event_time=datetime(2026, 1, 5, 10, 2, 5, tzinfo=timezone.utc),
            )
        )

        self.assertEqual(2, len(result.closed_candles))
        first = result.closed_candles[0]
        synthetic = result.closed_candles[1]

        self.assertTrue(first.closed)
        self.assertEqual(100.0, first.open)
        self.assertEqual(101.0, first.high)
        self.assertEqual(100.0, first.low)
        self.assertEqual(101.0, first.close)
        self.assertEqual(3.0, first.volume)
        self.assertEqual(2, first.trade_count)

        self.assertTrue(synthetic.closed)
        self.assertEqual(101.0, synthetic.open)
        self.assertEqual(101.0, synthetic.high)
        self.assertEqual(101.0, synthetic.low)
        self.assertEqual(101.0, synthetic.close)
        self.assertEqual(0.0, synthetic.volume)


if __name__ == "__main__":
    unittest.main()

