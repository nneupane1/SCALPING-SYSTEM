from __future__ import annotations

import unittest

from backend.app.core.models import ClosedTrade, Side
from backend.app.portfolio.analytics import build_forensic_report
from backend.tests.helpers import make_candle


class PortfolioAnalyticsTests(unittest.TestCase):
    def test_forensic_report_groups_trades_by_state_session_quality_and_tags(self) -> None:
        opened = make_candle(
            minute_offset=0,
            open_price=100.0,
            high=101.0,
            low=99.5,
            close=100.8,
            volume=10.0,
            timeframe="5m",
        ).close_time
        closed = make_candle(
            minute_offset=5,
            open_price=100.8,
            high=101.5,
            low=100.4,
            close=101.2,
            volume=12.0,
            timeframe="5m",
        ).close_time
        trades = (
            ClosedTrade(
                symbol="BTCUSDT",
                timeframe="5m",
                side=Side.LONG,
                opened_at=opened,
                closed_at=closed,
                entry_price=100.0,
                exit_price=101.0,
                initial_quantity=1.0,
                realized_pnl=1.0,
                realized_r=1.0,
                reason="runner exit",
                tags=("outcome:clean_continuation", "market_state:trend"),
                metadata={
                    "market_state": "trend",
                    "session_phase": "opening",
                    "setup_quality_label": "elite",
                },
            ),
            ClosedTrade(
                symbol="BTCUSDT",
                timeframe="5m",
                side=Side.LONG,
                opened_at=opened,
                closed_at=closed,
                entry_price=100.0,
                exit_price=99.5,
                initial_quantity=1.0,
                realized_pnl=-0.5,
                realized_r=-0.5,
                reason="early failure exit due to missing follow-through",
                tags=("outcome:loss_compression", "market_state:volatile_chop"),
                metadata={
                    "market_state": "volatile_chop",
                    "session_phase": "closing",
                    "setup_quality_label": "marginal",
                },
            ),
        )

        report = build_forensic_report(trades)

        self.assertEqual(2, report.overall.trade_count)
        self.assertEqual({"trend", "volatile_chop"}, {row.bucket for row in report.by_market_state})
        self.assertEqual({"opening", "closing"}, {row.bucket for row in report.by_session_phase})
        self.assertEqual({"elite", "marginal"}, {row.bucket for row in report.by_quality})
        self.assertEqual(
            {"runner exit", "early failure exit due to missing follow-through"},
            {row.bucket for row in report.by_reason},
        )
        tag_buckets = {row.bucket for row in report.by_tag}
        self.assertIn("outcome:clean_continuation", tag_buckets)
        self.assertIn("outcome:loss_compression", tag_buckets)


if __name__ == "__main__":
    unittest.main()
