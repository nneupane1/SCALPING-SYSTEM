from __future__ import annotations

import unittest
from datetime import datetime

from backend.app.config.models import SessionWindow, SessionsConfig, StrategyFilterConfig
from backend.app.core.models import MarketSnapshot
from backend.app.strategies.session_context import assess_session


class SessionContextTests(unittest.TestCase):
    def test_naive_snapshot_timestamp_is_interpreted_as_utc(self) -> None:
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            generated_at=datetime(2026, 1, 5, 13, 30, 0),
            candles={},
        )
        sessions = SessionsConfig(
            enabled=True,
            timezone="Europe/Berlin",
            active_windows=(
                SessionWindow(name="new_york", start="14:30", end="17:30"),
            ),
        )
        tuning = StrategyFilterConfig.SessionTuningConfig(
            enabled=True,
            block_outside_sessions=True,
            opening_minutes=60,
            closing_buffer_minutes=30,
        )

        assessment = assess_session(
            snapshot=snapshot,
            sessions_config=sessions,
            tuning_config=tuning,
        )

        self.assertTrue(assessment.active)
        self.assertEqual("new_york", assessment.session_name)
        self.assertEqual("opening", assessment.phase)


if __name__ == "__main__":
    unittest.main()
