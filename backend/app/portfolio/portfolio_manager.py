"""Portfolio state management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.app.core.models import ClosedTrade, OpenPosition, PortfolioSnapshot

from .journal import Journal


@dataclass(frozen=True)
class DayPerformanceSummary:
    """Intraday performance snapshot used for discipline and risk shaping."""

    trade_count: int
    realized_pnl: float
    realized_r: float
    win_count: int
    loss_count: int
    consecutive_losses: int


class PortfolioManager:
    """Track current equity, open position, and closed-trade outcomes."""

    def __init__(self, starting_equity: float, journal: Journal) -> None:
        self.starting_equity = starting_equity
        self.current_equity = starting_equity
        self.realized_pnl = 0.0
        self.peak_equity = starting_equity
        self.active_position: OpenPosition | None = None
        self.closed_trades: list[ClosedTrade] = []
        self.win_count = 0
        self.loss_count = 0
        self.journal = journal

    def open_position(self, position: OpenPosition) -> None:
        if self.active_position is not None:
            raise ValueError("PortfolioManager currently supports a single active position.")
        self.active_position = position
        self.journal.record(
            "execution",
            "opened position",
            symbol=position.symbol,
            side=position.side.value,
            entry_price=position.entry_price,
            stop_price=position.stop_price,
            quantity=position.initial_quantity,
            session=position.source_signal.metadata.get("session_name"),
            market_state=position.source_signal.metadata.get("market_state"),
            quality=position.source_signal.metadata.get("setup_quality_label"),
        )

    def sync_active_position(self, position: OpenPosition) -> None:
        if position.remaining_quantity <= 0:
            self.active_position = None
        else:
            self.active_position = position

    def close_position(self, trade: ClosedTrade) -> None:
        self.closed_trades.append(trade)
        self.realized_pnl += trade.realized_pnl
        self.current_equity = self.starting_equity + self.realized_pnl
        self.peak_equity = max(self.peak_equity, self.current_equity)
        if trade.realized_pnl > 0:
            self.win_count += 1
        elif trade.realized_pnl < 0:
            self.loss_count += 1
        self.active_position = None
        self.journal.record(
            "portfolio",
            "closed trade",
            symbol=trade.symbol,
            side=trade.side.value,
            pnl=trade.realized_pnl,
            r=trade.realized_r,
            reason=trade.reason,
            tags=trade.tags,
            market_state=trade.metadata.get("market_state"),
            session=trade.metadata.get("session_name"),
            quality=trade.metadata.get("setup_quality_label"),
        )

    def snapshot(self) -> PortfolioSnapshot:
        drawdown = self.current_equity - self.peak_equity
        return PortfolioSnapshot(
            starting_equity=self.starting_equity,
            current_equity=self.current_equity,
            realized_pnl=self.realized_pnl,
            closed_trade_count=len(self.closed_trades),
            win_count=self.win_count,
            loss_count=self.loss_count,
            peak_equity=self.peak_equity,
            drawdown=drawdown,
            active_position=self.active_position,
        )

    def build_day_summary(self, reference_time: datetime, timezone_name: str) -> DayPerformanceSummary:
        local_day = reference_time.astimezone(ZoneInfo(timezone_name)).date()
        day_trades = [
            trade
            for trade in self.closed_trades
            if trade.closed_at.astimezone(ZoneInfo(timezone_name)).date() == local_day
        ]
        consecutive_losses = 0
        for trade in reversed(day_trades):
            if trade.realized_pnl < 0:
                consecutive_losses += 1
                continue
            break
        return DayPerformanceSummary(
            trade_count=len(day_trades),
            realized_pnl=sum(trade.realized_pnl for trade in day_trades),
            realized_r=sum(trade.realized_r for trade in day_trades),
            win_count=sum(1 for trade in day_trades if trade.realized_pnl > 0),
            loss_count=sum(1 for trade in day_trades if trade.realized_pnl < 0),
            consecutive_losses=consecutive_losses,
        )
