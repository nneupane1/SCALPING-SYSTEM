"""Portfolio analytics."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.models import ClosedTrade


@dataclass(frozen=True)
class PerformanceStats:
    """Aggregate trade statistics."""

    trade_count: int
    win_rate: float
    average_r: float
    profit_factor: float


def build_performance_stats(trades: tuple[ClosedTrade, ...]) -> PerformanceStats:
    if not trades:
        return PerformanceStats(trade_count=0, win_rate=0.0, average_r=0.0, profit_factor=0.0)

    gross_profit = sum(max(0.0, trade.realized_pnl) for trade in trades)
    gross_loss = abs(sum(min(0.0, trade.realized_pnl) for trade in trades))
    wins = sum(1 for trade in trades if trade.realized_pnl > 0)
    average_r = sum(trade.realized_r for trade in trades) / len(trades)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    return PerformanceStats(
        trade_count=len(trades),
        win_rate=wins / len(trades),
        average_r=average_r,
        profit_factor=profit_factor,
    )

