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

