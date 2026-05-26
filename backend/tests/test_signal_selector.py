from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.app.config.models import RiskConfig
from backend.app.core.models import Side, TradeSignal
from backend.app.portfolio.journal import Journal
from backend.app.portfolio.portfolio_manager import PortfolioManager
from backend.app.portfolio.signal_selector import SignalSelector
from backend.app.risk.risk_manager import RiskManager


class SignalSelectorTests(unittest.TestCase):
    def test_selector_picks_highest_ranked_signals_within_portfolio_risk_cap(self) -> None:
        risk_config = RiskConfig.from_mapping(
            {
                "risk": {
                    "risk_per_trade": 0.005,
                    "max_open_positions": 2,
                    "max_total_open_risk_fraction": 0.01,
                    "max_positions_per_symbol": 1,
                    "max_position_notional": 25000,
                },
                "management": {},
                "execution": {},
            }
        )
        portfolio = PortfolioManager(starting_equity=25_000.0, journal=Journal())
        selector = SignalSelector(
            portfolio_manager=portfolio,
            risk_manager=RiskManager(risk_config),
        )

        high_rank = self._signal(
            symbol="BTCUSDT",
            confidence=0.82,
            context_alignment="aligned",
            market_state="trend",
            session_phase="opening",
            setup_execution_band="A",
            entry_timing_score=0.78,
            scanner_setup_score=0.80,
        )
        mid_rank = self._signal(
            symbol="ETHUSDT",
            confidence=0.76,
            context_alignment="neutral",
            market_state="transition",
            session_phase="core",
            setup_execution_band="A",
            entry_timing_score=0.68,
            scanner_setup_score=0.70,
        )
        low_rank = self._signal(
            symbol="SOLUSDT",
            confidence=0.61,
            context_alignment="conflicting",
            market_state="range",
            session_phase="closing",
            setup_execution_band="B",
            entry_timing_score=0.52,
            scanner_setup_score=0.55,
        )

        selected = selector.select((low_rank, high_rank, mid_rank))

        self.assertEqual(("BTCUSDT", "ETHUSDT"), tuple(item.signal.symbol for item in selected))
        self.assertEqual(2, len(selected))

    def _signal(
        self,
        *,
        symbol: str,
        confidence: float,
        context_alignment: str,
        market_state: str,
        session_phase: str,
        setup_execution_band: str,
        entry_timing_score: float,
        scanner_setup_score: float,
    ) -> TradeSignal:
        generated_at = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
        return TradeSignal(
            strategy_name="pullback_scalp",
            symbol=symbol,
            timeframe="5m",
            side=Side.LONG,
            generated_at=generated_at,
            entry_price=100.0,
            stop_price=98.0,
            first_target_price=102.0,
            confidence=confidence,
            reasons=("test",),
            metadata={
                "context_alignment": context_alignment,
                "market_state": market_state,
                "session_phase": session_phase,
                "setup_execution_band": setup_execution_band,
                "entry_timing_score": entry_timing_score,
                "scanner_setup_score": scanner_setup_score,
                "risk_fraction_multiplier": 1.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
