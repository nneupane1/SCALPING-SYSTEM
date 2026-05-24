"""Portfolio analytics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.app.core.models import ClosedTrade


@dataclass(frozen=True)
class PerformanceStats:
    """Aggregate trade statistics."""

    trade_count: int
    win_rate: float
    average_r: float
    profit_factor: float


@dataclass(frozen=True)
class BreakdownStats:
    """Performance grouped by a categorical trait."""

    bucket: str
    trade_count: int
    win_rate: float
    average_r: float
    total_pnl: float
    profit_factor: float


@dataclass(frozen=True)
class ForensicReport:
    """Structured report for learning from tagged trade populations."""

    overall: PerformanceStats
    by_market_state: tuple[BreakdownStats, ...]
    by_session_phase: tuple[BreakdownStats, ...]
    by_quality: tuple[BreakdownStats, ...]
    by_reason: tuple[BreakdownStats, ...]
    by_tag: tuple[BreakdownStats, ...]


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


def build_breakdown_by_metadata(
    trades: tuple[ClosedTrade, ...],
    *,
    metadata_key: str,
) -> tuple[BreakdownStats, ...]:
    """Group trades by one metadata field such as market state or session phase."""

    buckets: dict[str, list[ClosedTrade]] = defaultdict(list)
    for trade in trades:
        raw_value = trade.metadata.get(metadata_key, "unknown")
        bucket = "unknown" if raw_value in (None, "") else str(raw_value)
        buckets[bucket].append(trade)
    return _materialize_breakdowns(buckets)


def build_breakdown_by_reason(trades: tuple[ClosedTrade, ...]) -> tuple[BreakdownStats, ...]:
    """Group trades by terminal exit reason."""

    buckets: dict[str, list[ClosedTrade]] = defaultdict(list)
    for trade in trades:
        buckets[str(trade.reason)].append(trade)
    return _materialize_breakdowns(buckets)


def build_breakdown_by_tag(trades: tuple[ClosedTrade, ...]) -> tuple[BreakdownStats, ...]:
    """Group trades by explicit journal tags."""

    buckets: dict[str, list[ClosedTrade]] = defaultdict(list)
    for trade in trades:
        if not trade.tags:
            buckets["untagged"].append(trade)
            continue
        for tag in trade.tags:
            buckets[str(tag)].append(trade)
    return _materialize_breakdowns(buckets)


def build_forensic_report(trades: tuple[ClosedTrade, ...]) -> ForensicReport:
    """Build a structured learning report over the closed-trade population."""

    return ForensicReport(
        overall=build_performance_stats(trades),
        by_market_state=build_breakdown_by_metadata(trades, metadata_key="market_state"),
        by_session_phase=build_breakdown_by_metadata(trades, metadata_key="session_phase"),
        by_quality=build_breakdown_by_metadata(trades, metadata_key="setup_quality_label"),
        by_reason=build_breakdown_by_reason(trades),
        by_tag=build_breakdown_by_tag(trades),
    )


def _materialize_breakdowns(buckets: dict[str, list[ClosedTrade]]) -> tuple[BreakdownStats, ...]:
    rows: list[BreakdownStats] = []
    for bucket, bucket_trades in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
        stats = build_performance_stats(tuple(bucket_trades))
        rows.append(
            BreakdownStats(
                bucket=bucket,
                trade_count=stats.trade_count,
                win_rate=stats.win_rate,
                average_r=stats.average_r,
                total_pnl=sum(trade.realized_pnl for trade in bucket_trades),
                profit_factor=stats.profit_factor,
            )
        )
    return tuple(rows)
