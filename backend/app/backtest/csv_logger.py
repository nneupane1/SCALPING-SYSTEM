"""CSV loggers for backtest outputs."""

from __future__ import annotations

import csv
from pathlib import Path

from backend.app.core.models import ClosedTrade


class TradeCsvLogger:
    """Append closed trades to a CSV file."""

    FIELDNAMES = [
        "symbol",
        "timeframe",
        "side",
        "opened_at",
        "closed_at",
        "entry_price",
        "exit_price",
        "initial_quantity",
        "realized_pnl",
        "realized_r",
        "reason",
        "notes",
        "tags",
        "market_state",
        "context_alignment",
        "session_name",
        "session_phase",
        "setup_quality_label",
        "setup_quality_score",
        "day_feedback_reason",
        "day_trade_count",
        "bars_held",
        "best_r_multiple",
        "worst_r_multiple",
        "first_target_hit_after_bars",
        "follow_through_state",
    ]

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self, *, resume: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if resume and self.path.exists():
            return
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            writer.writeheader()

    def append(self, trade: ClosedTrade) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            writer.writerow(
                {
                    "symbol": trade.symbol,
                    "timeframe": trade.timeframe,
                    "side": trade.side.value,
                    "opened_at": trade.opened_at.isoformat(),
                    "closed_at": trade.closed_at.isoformat(),
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "initial_quantity": trade.initial_quantity,
                    "realized_pnl": trade.realized_pnl,
                    "realized_r": trade.realized_r,
                    "reason": trade.reason,
                    "notes": " | ".join(trade.notes),
                    "tags": " | ".join(trade.tags),
                    "market_state": trade.metadata.get("market_state"),
                    "context_alignment": trade.metadata.get("context_alignment"),
                    "session_name": trade.metadata.get("session_name"),
                    "session_phase": trade.metadata.get("session_phase"),
                    "setup_quality_label": trade.metadata.get("setup_quality_label"),
                    "setup_quality_score": trade.metadata.get("setup_quality_score"),
                    "day_feedback_reason": trade.metadata.get("day_feedback_reason"),
                    "day_trade_count": trade.metadata.get("day_trade_count"),
                    "bars_held": trade.metadata.get("bars_held"),
                    "best_r_multiple": trade.metadata.get("best_r_multiple"),
                    "worst_r_multiple": trade.metadata.get("worst_r_multiple"),
                    "first_target_hit_after_bars": trade.metadata.get("first_target_hit_after_bars"),
                    "follow_through_state": trade.metadata.get("follow_through_state"),
                }
            )


class EquityCsvLogger:
    """Append equity snapshots to a CSV file."""

    FIELDNAMES = ["timestamp", "equity"]

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self, *, resume: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if resume and self.path.exists():
            return
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            writer.writeheader()

    def append(self, *, timestamp: str, equity: float) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            writer.writerow({"timestamp": timestamp, "equity": equity})
