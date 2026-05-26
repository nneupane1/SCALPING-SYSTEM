"""CSV loggers for backtest outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from zoneinfo import ZoneInfo

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
        "setup_execution_band",
        "setup_quality_score",
        "scanner_setup_score",
        "scanner_impulse_tier",
        "scanner_pullback_quality_label",
        "entry_timing_score",
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
                    "setup_execution_band": trade.metadata.get("setup_execution_band"),
                    "setup_quality_score": trade.metadata.get("setup_quality_score"),
                    "scanner_setup_score": trade.metadata.get("scanner_setup_score"),
                    "scanner_impulse_tier": trade.metadata.get("scanner_impulse_tier"),
                    "scanner_pullback_quality_label": trade.metadata.get("scanner_pullback_quality_label"),
                    "entry_timing_score": trade.metadata.get("entry_timing_score"),
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
        "symbol",
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
                        "symbol": window.symbol,
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


class DailySummaryCsvLogger:
    """Persist one row per local trading day for cadence and pnl analysis."""

    FIELDNAMES = [
        "date_local",
        "closed_trades",
        "wins",
        "losses",
        "win_rate",
        "realized_pnl",
        "realized_r",
        "avg_r",
        "best_trade_r",
        "worst_trade_r",
        "ending_equity",
        "good_day_target_hit",
    ]

    def __init__(self, path: Path) -> None:
        self.path = path

    def write_all(
        self,
        trades: list[ClosedTrade],
        *,
        timezone_name: str,
        starting_equity: float,
        good_day_threshold_r: float,
    ) -> list[dict[str, object]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        zone = ZoneInfo(timezone_name)
        cumulative_pnl = 0.0
        buckets: dict[str, dict[str, object]] = {}
        for trade in sorted(trades, key=lambda item: item.closed_at):
            local_date = trade.closed_at.astimezone(zone).date().isoformat()
            bucket = buckets.setdefault(
                local_date,
                {
                    "date_local": local_date,
                    "closed_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "realized_pnl": 0.0,
                    "realized_r": 0.0,
                    "best_trade_r": float("-inf"),
                    "worst_trade_r": float("inf"),
                    "ending_equity": starting_equity,
                },
            )
            bucket["closed_trades"] = int(bucket["closed_trades"]) + 1
            bucket["realized_pnl"] = float(bucket["realized_pnl"]) + trade.realized_pnl
            bucket["realized_r"] = float(bucket["realized_r"]) + trade.realized_r
            bucket["best_trade_r"] = max(float(bucket["best_trade_r"]), trade.realized_r)
            bucket["worst_trade_r"] = min(float(bucket["worst_trade_r"]), trade.realized_r)
            if trade.realized_pnl > 0:
                bucket["wins"] = int(bucket["wins"]) + 1
            elif trade.realized_pnl < 0:
                bucket["losses"] = int(bucket["losses"]) + 1
            cumulative_pnl += trade.realized_pnl
            bucket["ending_equity"] = starting_equity + cumulative_pnl

        rows: list[dict[str, object]] = []
        for date_local in sorted(buckets):
            bucket = buckets[date_local]
            closed_trades = int(bucket["closed_trades"])
            realized_r = float(bucket["realized_r"])
            rows.append(
                {
                    "date_local": bucket["date_local"],
                    "closed_trades": closed_trades,
                    "wins": int(bucket["wins"]),
                    "losses": int(bucket["losses"]),
                    "win_rate": 0.0 if closed_trades == 0 else int(bucket["wins"]) / closed_trades,
                    "realized_pnl": float(bucket["realized_pnl"]),
                    "realized_r": realized_r,
                    "avg_r": 0.0 if closed_trades == 0 else realized_r / closed_trades,
                    "best_trade_r": 0.0 if closed_trades == 0 else float(bucket["best_trade_r"]),
                    "worst_trade_r": 0.0 if closed_trades == 0 else float(bucket["worst_trade_r"]),
                    "ending_equity": float(bucket["ending_equity"]),
                    "good_day_target_hit": realized_r >= good_day_threshold_r,
                }
            )

        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        return rows


class DiagnosticsJsonLogger:
    """Persist nested forensic diagnostics for one completed backtest."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
