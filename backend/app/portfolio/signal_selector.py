"""Cross-symbol signal ranking and portfolio-aware selection."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.models import RiskPlan, TradeSignal


@dataclass(frozen=True)
class RankedSignal:
    """A signal paired with its tentative portfolio rank and risk plan."""

    signal: TradeSignal
    risk_plan: RiskPlan
    rank_score: float


class SignalSelector:
    """Choose the strongest signals that fit the shared account risk budget."""

    def __init__(self, *, portfolio_manager, risk_manager) -> None:
        self.portfolio_manager = portfolio_manager
        self.risk_manager = risk_manager

    def select(self, signals: tuple[TradeSignal, ...]) -> tuple[RankedSignal, ...]:
        limits = self.risk_manager.risk_config.risk
        available_slots = max(0, limits.max_open_positions - self.portfolio_manager.open_position_count)
        if available_slots <= 0 or not signals:
            return ()

        equity = self.portfolio_manager.current_equity
        max_total_open_risk = equity * limits.max_total_open_risk_fraction
        current_open_risk = self.portfolio_manager.total_open_risk_amount()
        selected: list[RankedSignal] = []
        selected_risk = 0.0

        candidates: list[tuple[float, TradeSignal, RiskPlan]] = []
        for signal in signals:
            if self._active_count_for_symbol(signal.symbol) >= limits.max_positions_per_symbol:
                continue
            try:
                risk_plan = self.risk_manager.build_plan(signal=signal, equity=equity)
            except ValueError:
                continue
            candidates.append((self._rank_score(signal), signal, risk_plan))

        for rank_score, signal, risk_plan in sorted(candidates, key=self._sort_key, reverse=True):
            if len(selected) >= available_slots:
                break
            projected_risk = current_open_risk + selected_risk + risk_plan.risk_amount
            if max_total_open_risk > 0 and projected_risk > max_total_open_risk + 1e-9:
                continue
            selected.append(
                RankedSignal(
                    signal=signal,
                    risk_plan=risk_plan,
                    rank_score=rank_score,
                )
            )
            selected_risk += risk_plan.risk_amount

        return tuple(selected)

    def _sort_key(self, candidate: tuple[float, TradeSignal, RiskPlan]) -> tuple[float, float, str]:
        rank_score, signal, risk_plan = candidate
        return (
            rank_score,
            signal.confidence,
            signal.symbol,
        )

    def _rank_score(self, signal: TradeSignal) -> float:
        metadata = signal.metadata
        band = str(metadata.get("setup_execution_band", "X")).upper()
        context = str(metadata.get("context_alignment", "neutral")).lower()
        market_state = str(metadata.get("market_state", "unknown")).lower()
        session_phase = str(metadata.get("session_phase", "unknown")).lower()
        entry_timing = float(metadata.get("entry_timing_score", 0.0) or 0.0)
        scanner_setup = float(metadata.get("scanner_setup_score", 0.0) or 0.0)

        band_bonus = {"A": 0.18, "B": 0.07}.get(band, 0.0)
        context_bonus = {"aligned": 0.10, "neutral": 0.03, "conflicting": -0.08}.get(context, 0.0)
        market_bonus = {
            "trend": 0.10,
            "transition": 0.06,
            "range": 0.0,
            "compression": -0.03,
            "volatile_chop": -0.20,
        }.get(market_state, 0.0)
        session_bonus = {"opening": 0.05, "core": 0.03, "closing": -0.04}.get(session_phase, 0.0)
        return (
            signal.confidence
            + band_bonus
            + context_bonus
            + market_bonus
            + session_bonus
            + (entry_timing * 0.30)
            + (scanner_setup * 0.22)
        )

    def _active_count_for_symbol(self, symbol: str) -> int:
        return 1 if self.portfolio_manager.position_for_symbol(symbol) is not None else 0
