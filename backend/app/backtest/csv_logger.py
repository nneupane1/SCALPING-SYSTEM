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


class GapCsvLogger:
    """Persist backtest gap windows and the applied exclusion policy."""

    FIELDNAMES = [
        "gap_id",
        "previous_base_timestamp",
        "next_base_timestamp",
        "missing_start",
        "missing_end",
        "missing_minutes",
        "previous_execution_index",
        "previous_execution_close",
        "next_execution_index",
        "next_execution_open",
        "next_execution_close",
        "missing_execution_bars",
        "blocked_entry_start_index",
        "blocked_entry_end_index",
        "force_flat_before_gap",
        "post_gap_cooldown_bars",
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

    def write_all(self, windows) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            for window in windows:
                writer.writerow(
                    {
                        "gap_id": window.gap_id,
                        "previous_base_timestamp": window.previous_base_timestamp.isoformat(),
                        "next_base_timestamp": window.next_base_timestamp.isoformat(),
                        "missing_start": window.missing_start.isoformat(),
                        "missing_end": window.missing_end.isoformat(),
                        "missing_minutes": window.missing_minutes,
                        "previous_execution_index": window.previous_execution_index,
                        "previous_execution_close": None if window.previous_execution_close is None else window.previous_execution_close.isoformat(),
                        "next_execution_index": window.next_execution_index,
                        "next_execution_open": None if window.next_execution_open is None else window.next_execution_open.isoformat(),
                        "next_execution_close": None if window.next_execution_close is None else window.next_execution_close.isoformat(),
                        "missing_execution_bars": window.missing_execution_bars,
                        "blocked_entry_start_index": window.blocked_entry_start_index,
                        "blocked_entry_end_index": window.blocked_entry_end_index,
                        "force_flat_before_gap": window.force_flat_before_gap,
                        "post_gap_cooldown_bars": window.post_gap_cooldown_bars,
                    }
                )
