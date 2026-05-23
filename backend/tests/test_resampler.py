from __future__ import annotations

import unittest

from backend.app.data.resampler import TimeframeResampler

from backend.tests.helpers import make_candle


class TimeframeResamplerTests(unittest.TestCase):
    def test_resampler_builds_closed_five_minute_candle(self) -> None:
        candles = tuple(
            make_candle(
                minute_offset=index,
                open_price=100.0 + index,
                high=101.0 + index,
                low=99.5 + index,
                close=100.5 + index,
                volume=10.0 + index,
                timeframe="1m",
            )
            for index in range(5)
        )
        resampler = TimeframeResampler(base_timeframe="1m")

        result = resampler.resample(candles, "5m")

        self.assertEqual(1, len(result))
        candle = result[0]
        self.assertEqual("5m", candle.timeframe)
        self.assertEqual(100.0, candle.open)
        self.assertEqual(105.0, candle.high)
        self.assertEqual(99.5, candle.low)
        self.assertEqual(104.5, candle.close)
        self.assertEqual(sum(10.0 + index for index in range(5)), candle.volume)


if __name__ == "__main__":
    unittest.main()
