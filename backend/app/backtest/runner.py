"""Checkpointed backtest runner built on top of the replay engine."""

from __future__ import annotations

from collections import defaultdict
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from zoneinfo import ZoneInfo

from backend.app.config.models import ConfigBundle, history_path_label
from backend.app.core import EngineCycleResult, JsonCheckpointStore
from backend.app.core.events import Event, EventTopic
from backend.app.core.models import ManagementAction, ManagementDecision
from backend.app.core.orchestrator import build_runtime
from backend.app.data import MarketDataDownloader, TimeframeBuilder, dataframe_to_candles
from backend.app.portfolio.signal_selector import SignalSelector
from backend.app.replay import MultiAssetReplayEngine

from .csv_logger import (
    DailySummaryCsvLogger,
    DiagnosticsJsonLogger,
    EquityCsvLogger,
    GapCsvLogger,
    TradeCsvLogger,
)


@dataclass(frozen=True)
class BacktestGapWindow:
    """One detected historical outage window mapped into execution-candle space."""

    symbol: str
    gap_id: int
    previous_base_timestamp: datetime
    next_base_timestamp: datetime
    missing_start: datetime
    missing_end: datetime
    missing_minutes: int
    previous_execution_index: int | None
    previous_execution_close: datetime | None
    next_execution_index: int | None
    next_execution_open: datetime | None
    next_execution_close: datetime | None
    missing_execution_bars: int
    blocked_entry_start_index: int | None
    blocked_entry_end_index: int | None
    force_flat_before_gap: bool
    post_gap_cooldown_bars: int


@dataclass(frozen=True)
class GapStepPolicy:
    """How one execution step should behave around a known outage window."""

    gap_ids: tuple[int, ...]
    phases: tuple[str, ...]
    block_entries: bool
    force_flat: bool
    messages: tuple[str, ...]


@dataclass(frozen=True)
class BacktestSummary:
    """Final high-level backtest result."""

    symbol: str
    execution_timeframe: str
    start_date: str
    end_date: str
    steps_processed: int
    closed_trades: int
    current_equity: float
    realized_pnl: float
    output_dir: Path
    gap_windows: int = 0
    gap_blocked_steps: int = 0
    gap_forced_exits: int = 0


class BacktestRunner:
    """Run a checkpointed historical simulation over saved OHLCV history."""

    def __init__(
        self,
        config: ConfigBundle,
        *,
        downloader: MarketDataDownloader | None = None,
        timeframe_builder: TimeframeBuilder | None = None,
        progress_callback=None,
    ) -> None:
        self.config = config
        self.progress_callback = progress_callback
        self.downloader = downloader or MarketDataDownloader(config, progress_callback=progress_callback)
        self.timeframe_builder = timeframe_builder or TimeframeBuilder(config, progress_callback=progress_callback)

    def _emit(self, event_type: str, **payload: object) -> None:
        if callable(self.progress_callback):
            self.progress_callback(event_type, **payload)

    def _log(self, message: str, *, level: str = "info") -> None:
        if callable(self.progress_callback):
            self._emit("event", level=level, message=message)
            return
        print(message)

    def run(
        self,
        *,
        symbol: str | None = None,
        symbols: tuple[str, ...] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> BacktestSummary:
        symbols = self._resolve_symbols(symbol=symbol, symbols=symbols)
        symbol_label = ", ".join(symbols)
        symbol_scope = self._symbol_scope_label(symbols)
        start_date = start_date or self.config.system.history.start_date
        end_date = end_date or self.config.system.history.end_date
        execution_timeframe = self.config.system.market.execution_timeframe
        profile = self.config.strategy.resolve_profile(execution_timeframe)
        clock_timeframe = profile.clock_timeframe
        self._emit(
            "phase",
            status="running",
            phase="preparing backtest",
            detail=f"{symbol_label} | {start_date} -> {end_date} | clock {clock_timeframe}",
        )

        candles_by_symbol: dict[str, dict[str, tuple]] = {}
        gap_windows_all: list[BacktestGapWindow] = []
        gap_policies_by_symbol: dict[str, dict[int, GapStepPolicy]] = {}
        for active_symbol in symbols:
            df_1m = self.downloader.fetch_full_history(
                symbol=active_symbol,
                interval=self.config.system.market.base_timeframe,
                start_date=start_date,
                end_date=end_date,
            )
            frames = self.timeframe_builder.build_timeframes_and_save(
                df_1m,
                symbol=active_symbol,
                start_date=start_date,
                end_date=end_date,
            )
            candles_by_timeframe = {
                timeframe: dataframe_to_candles(
                    frame,
                    symbol=active_symbol,
                    timeframe=timeframe,
                    index_is_close_time=(timeframe != self.config.system.market.base_timeframe),
                )
                for timeframe, frame in frames.items()
            }
            candles_by_symbol[active_symbol] = candles_by_timeframe
            execution_series = candles_by_timeframe.get(execution_timeframe, ())
            gap_windows, gap_policies = self._build_gap_policy(
                symbol=active_symbol,
                df_1m=df_1m,
                execution_series=execution_series,
                execution_timeframe=execution_timeframe,
            )
            gap_windows_all.extend(gap_windows)
            gap_policies_by_symbol[active_symbol] = gap_policies

        runtime = build_runtime(self.config)
        selector = SignalSelector(
            portfolio_manager=runtime.portfolio_manager,
            risk_manager=runtime.engine.risk_manager,
        )
        rejection_counts: dict[str, int] = defaultdict(int)
        scanner_state_counts: dict[str, int] = defaultdict(int)
        accepted_signal_counts: dict[str, int] = defaultdict(int)
        accepted_quality_counts: dict[str, int] = defaultdict(int)
        accepted_session_counts: dict[str, int] = defaultdict(int)
        accepted_market_state_counts: dict[str, int] = defaultdict(int)
        runtime.event_bus.subscribe(
            EventTopic.SCANNER_UPDATED,
            lambda event: self._register_scanner_rejection(
                rejection_counts=rejection_counts,
                payload=event.payload,
            ),
        )
        runtime.event_bus.subscribe(
            EventTopic.SCANNER_UPDATED,
            lambda event: self._register_scanner_state(
                scanner_state_counts=scanner_state_counts,
                payload=event.payload,
            ),
        )
        runtime.event_bus.subscribe(
            EventTopic.HEALTH,
            lambda event: self._register_health_rejection(
                rejection_counts=rejection_counts,
                payload=event.payload,
            ),
        )
        runtime.event_bus.subscribe(
            EventTopic.SIGNAL_EMITTED,
            lambda event: self._register_signal_acceptance(
                accepted_signal_counts=accepted_signal_counts,
                accepted_quality_counts=accepted_quality_counts,
                accepted_session_counts=accepted_session_counts,
                accepted_market_state_counts=accepted_market_state_counts,
                payload=event.payload,
            ),
        )
        replay_engine = MultiAssetReplayEngine(
            clock_timeframe=clock_timeframe,
            execution_timeframe=execution_timeframe,
            candles_by_symbol=candles_by_symbol,
        )

        backtest_cfg = self.config.system.backtest
        output_dir = Path(backtest_cfg.output_dir)
        checkpoint_path = (
            output_dir
            / backtest_cfg.checkpoint_dir
            / (
                f"{symbol_scope}_{execution_timeframe}_{history_path_label(start_date)}"
                f"_to_{history_path_label(end_date)}{backtest_cfg.checkpoint_suffix}"
            )
        )
        checkpoint_store = JsonCheckpointStore(checkpoint_path)
        trade_logger = TradeCsvLogger(output_dir / "trades.csv")
        equity_logger = EquityCsvLogger(output_dir / "equity.csv")
        gap_logger = GapCsvLogger(output_dir / "gap_windows.csv")
        daily_summary_logger = DailySummaryCsvLogger(output_dir / "daily_summary.csv")
        diagnostics_logger = DiagnosticsJsonLogger(output_dir / "diagnostics.json")

        checkpoint = checkpoint_store.read() if backtest_cfg.resume_enabled else None
        resume_signature = self._resume_signature(symbols=symbols, execution_timeframe=execution_timeframe)
        if checkpoint and not self._checkpoint_compatible(checkpoint=checkpoint, resume_signature=resume_signature):
            self._log("Ignoring incompatible backtest checkpoint and starting fresh state.", level="warning")
            checkpoint = None
        resume = bool(checkpoint and not checkpoint.get("completed", False))
        trade_logger.initialize(resume=resume)
        equity_logger.initialize(resume=resume)
        if backtest_cfg.output_gap_windows:
            gap_logger.initialize(resume=resume)
            if not (resume and gap_logger.path.exists()):
                gap_logger.write_all(gap_windows_all)

        resume_index = int(checkpoint.get("next_index", 0)) if resume and checkpoint else 0
        gap_blocked_steps = 0
        gap_forced_exits = 0
        if resume_index > 0:
            self._log(f"Resuming backtest from checkpoint index {resume_index}", level="warning")
            gap_blocked_steps, gap_forced_exits = self._fast_forward(
                replay_engine=replay_engine,
                runtime=runtime,
                selector=selector,
                gap_policies_by_symbol=gap_policies_by_symbol,
                steps=resume_index,
            )

        save_every = max(1, backtest_cfg.save_every_steps)
        total_steps = replay_engine.total_steps
        update_stride = max(1, total_steps // 1000) if total_steps else 1
        simulated_start = self._parse_history_timestamp(start_date)
        simulated_end = self._parse_history_timestamp(end_date)
        last_ui_update_at = perf_counter()
        loop_started_at = last_ui_update_at
        self._emit(
            "phase",
            status="running",
            phase="running backtest",
                detail=(
                f"{symbol_scope} {execution_timeframe} | "
                f"{total_steps:,} {clock_timeframe} clock candles | "
                f"starting at step {resume_index:,}"
            ),
        )
        self._emit(
            "progress",
            description=f"Backtesting {symbol_scope} {execution_timeframe}",
            completed=resume_index,
            total=total_steps,
            status="running",
        )
        self._emit(
            "metrics",
            metrics=self._build_runtime_metrics(
                symbol=symbol_scope,
                start_date=start_date,
                end_date=end_date,
                total_steps=total_steps,
                steps_done=resume_index,
                simulated_at=simulated_start,
                simulated_progress=0.0,
                steps_per_second=0.0,
                eta_seconds=None,
                runtime=runtime,
                latest_trade=None,
                gap_windows=len(gap_windows_all),
                gap_blocked_steps=gap_blocked_steps,
                gap_forced_exits=gap_forced_exits,
                rejection_counts=rejection_counts,
            ),
        )
        while replay_engine.has_next():
            closed_before = len(runtime.portfolio_manager.closed_trades)
            batch_results, batch_blocked_steps, batch_forced_exits = self._advance_batch(
                replay_engine=replay_engine,
                runtime=runtime,
                selector=selector,
                gap_policies_by_symbol=gap_policies_by_symbol,
                emit_gap_events=True,
            )
            if not batch_results:
                break
            gap_blocked_steps += batch_blocked_steps
            gap_forced_exits += batch_forced_exits
            closed_after = len(runtime.portfolio_manager.closed_trades)
            if closed_after > closed_before:
                for trade in runtime.portfolio_manager.closed_trades[closed_before:closed_after]:
                    trade_logger.append(trade)
            latest_result = batch_results[-1]
            equity_logger.append(
                timestamp=latest_result.snapshot.generated_at.isoformat(),
                equity=runtime.portfolio_manager.current_equity,
            )
            now = perf_counter()
            should_refresh = (
                replay_engine.cursor.processed_steps % update_stride == 0
                or replay_engine.cursor.processed_steps == total_steps
                or closed_after > closed_before
                or now - last_ui_update_at >= 1.0
            )
            if should_refresh:
                elapsed_seconds = max(1e-9, now - loop_started_at)
                processed_since_loop_start = max(0, replay_engine.cursor.processed_steps - resume_index)
                steps_per_second = processed_since_loop_start / elapsed_seconds
                remaining_steps = max(0, total_steps - replay_engine.cursor.processed_steps)
                eta_seconds = (
                    remaining_steps / steps_per_second
                    if steps_per_second > 0
                    else None
                )
                simulated_at = latest_result.snapshot.generated_at
                simulated_progress = self._progress_ratio(
                    current=simulated_at,
                    start=simulated_start,
                    end=simulated_end,
                )
                latest_trade = (
                    runtime.portfolio_manager.closed_trades[-1]
                    if runtime.portfolio_manager.closed_trades
                    else None
                )
                self._emit(
                    "progress",
                    description=f"Backtesting {symbol_scope} {execution_timeframe}",
                    completed=replay_engine.cursor.processed_steps,
                    total=total_steps,
                    status="running",
                )
                self._emit(
                    "phase",
                    status="running",
                    phase="running backtest",
                    detail=(
                        f"{symbol_scope} {execution_timeframe} | "
                        f"simulated {simulated_at.isoformat()} | "
                        f"step {replay_engine.cursor.processed_steps:,} / {total_steps:,}"
                    ),
                )
                self._emit(
                    "metrics",
                    metrics=self._build_runtime_metrics(
                        symbol=symbol_scope,
                        start_date=start_date,
                        end_date=end_date,
                        total_steps=total_steps,
                        steps_done=replay_engine.cursor.processed_steps,
                        simulated_at=simulated_at,
                        simulated_progress=simulated_progress,
                        steps_per_second=steps_per_second,
                        eta_seconds=eta_seconds,
                        runtime=runtime,
                        latest_trade=latest_trade,
                        gap_windows=len(gap_windows_all),
                        gap_blocked_steps=gap_blocked_steps,
                        gap_forced_exits=gap_forced_exits,
                        rejection_counts=rejection_counts,
                    ),
                )
                last_ui_update_at = now
            if closed_after > closed_before:
                for trade in runtime.portfolio_manager.closed_trades[closed_before:closed_after]:
                    self._log(
                        (
                            f"Closed {trade.side.value} trade | "
                            f"{trade.realized_r:.2f}R | "
                            f"{trade.closed_at.isoformat()} | "
                            f"{trade.metadata.get('session_name', 'no_session')}"
                        ),
                        level="success" if trade.realized_r >= 0 else "warning",
                    )
            if backtest_cfg.enabled and replay_engine.cursor.processed_steps % save_every == 0:
                checkpoint_store.write(
                    {
                        "symbol": symbol_scope,
                        "symbols": list(symbols),
                        "execution_timeframe": execution_timeframe,
                        "start_date": start_date,
                        "end_date": end_date,
                        "next_index": replay_engine.cursor.processed_steps,
                        "closed_trades": len(runtime.portfolio_manager.closed_trades),
                        "equity": runtime.portfolio_manager.current_equity,
                        "resume_signature": resume_signature,
                        "completed": False,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        self._emit(
            "complete",
            status="completed",
            phase="backtest complete",
            detail=str(output_dir),
            metrics={
                "steps": replay_engine.cursor.processed_steps,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                "realized_pnl": f"{runtime.portfolio_manager.realized_pnl:.2f}",
                "gap_windows": len(gap_windows_all),
                "gap_blocked_steps": gap_blocked_steps,
                "gap_forced_exits": gap_forced_exits,
            },
        )
        checkpoint_store.write(
            {
                "symbol": symbol_scope,
                "symbols": list(symbols),
                "execution_timeframe": execution_timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "next_index": replay_engine.cursor.processed_steps,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": runtime.portfolio_manager.current_equity,
                "resume_signature": resume_signature,
                "completed": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        daily_rows = daily_summary_logger.write_all(
            runtime.portfolio_manager.closed_trades,
            timezone_name=self.config.system.sessions.timezone,
            starting_equity=self.config.system.account.initial_equity,
            good_day_threshold_r=self.config.risk.risk.good_day_threshold_r,
        )
        diagnostics_logger.write(
            self._build_diagnostics_payload(
                symbol=symbol_scope,
                execution_timeframe=execution_timeframe,
                start_date=start_date,
                end_date=end_date,
                runtime=runtime,
                total_steps=total_steps,
                steps_processed=replay_engine.cursor.processed_steps,
                scanner_state_counts=scanner_state_counts,
                accepted_signal_counts=accepted_signal_counts,
                accepted_quality_counts=accepted_quality_counts,
                accepted_session_counts=accepted_session_counts,
                accepted_market_state_counts=accepted_market_state_counts,
                rejection_counts=rejection_counts,
                gap_windows=len(gap_windows_all),
                gap_blocked_steps=gap_blocked_steps,
                gap_forced_exits=gap_forced_exits,
                daily_rows=daily_rows,
            )
        )

        return BacktestSummary(
            symbol=symbol_scope,
            execution_timeframe=execution_timeframe,
            start_date=start_date,
            end_date=end_date,
            steps_processed=replay_engine.cursor.processed_steps,
            closed_trades=len(runtime.portfolio_manager.closed_trades),
            current_equity=runtime.portfolio_manager.current_equity,
            realized_pnl=runtime.portfolio_manager.realized_pnl,
            output_dir=output_dir,
            gap_windows=len(gap_windows_all),
            gap_blocked_steps=gap_blocked_steps,
            gap_forced_exits=gap_forced_exits,
        )

    def _resolve_symbols(
        self,
        *,
        symbol: str | None,
        symbols: tuple[str, ...] | None,
    ) -> tuple[str, ...]:
        if symbols:
            normalized = tuple(str(item).strip().upper() for item in symbols if str(item).strip())
            if normalized:
                return tuple(dict.fromkeys(normalized))
        return self.config.system.market.resolved_symbols(symbol)

    def _symbol_scope_label(self, symbols: tuple[str, ...]) -> str:
        if len(symbols) == 1:
            return symbols[0]
        return "__".join(symbols)

    def _parse_history_timestamp(self, value: str) -> datetime:
        return datetime.fromisoformat(value.strip().replace(" ", "T")).replace(tzinfo=timezone.utc)

    def _progress_ratio(self, *, current: datetime, start: datetime, end: datetime) -> float:
        total_seconds = max(1.0, (end - start).total_seconds())
        elapsed_seconds = min(total_seconds, max(0.0, (current - start).total_seconds()))
        return elapsed_seconds / total_seconds

    def _build_runtime_metrics(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        total_steps: int,
        steps_done: int,
        simulated_at: datetime,
        simulated_progress: float,
        steps_per_second: float,
        eta_seconds: float | None,
        runtime,
        latest_trade,
        gap_windows: int,
        gap_blocked_steps: int,
        gap_forced_exits: int,
        rejection_counts: dict[str, int],
    ) -> dict[str, object]:
        berlin_time = simulated_at.astimezone(ZoneInfo(self.config.system.sessions.timezone))
        day_summary = runtime.portfolio_manager.build_day_summary(
            simulated_at,
            self.config.system.sessions.timezone,
        )
        profile = self.config.strategy.resolve_profile(self.config.system.market.execution_timeframe)
        metrics: dict[str, object] = {
            "symbol": symbol,
            "range": f"{start_date} -> {end_date}",
            "steps_done": steps_done,
            "total_steps": total_steps,
            "progress_pct": f"{(steps_done / total_steps * 100):.2f}%" if total_steps else "0.00%",
            "simulated_progress_pct": f"{simulated_progress * 100:.2f}%",
            "simulated_at_utc": simulated_at.isoformat(),
            "simulated_at_local": berlin_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "steps_per_sec": f"{steps_per_second:.2f}",
            "eta": self._format_duration(eta_seconds),
            "day_trade_count": day_summary.trade_count,
            "day_realized_r": f"{day_summary.realized_r:.2f}",
            "closed_trades": len(runtime.portfolio_manager.closed_trades),
            "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
            "realized_pnl": f"{runtime.portfolio_manager.realized_pnl:.2f}",
            "trigger_timeframe": profile.trigger_timeframe,
            "gap_windows": gap_windows,
            "gap_blocked_steps": gap_blocked_steps,
            "gap_forced_exits": gap_forced_exits,
            "last_trade_closed_at": "-" if latest_trade is None else latest_trade.closed_at.isoformat(),
            "last_trade_r": "-" if latest_trade is None else f"{latest_trade.realized_r:.2f}",
            "rejection_total": sum(rejection_counts.values()),
        }
        for index, (reason, count) in enumerate(self._top_rejections(rejection_counts), start=1):
            metrics[f"reject_{index}"] = f"{count}x {reason}"
        return metrics

    def _register_scanner_rejection(self, *, rejection_counts: dict[str, int], payload) -> None:
        if payload is None or getattr(payload, "is_tradeable", False):
            return
        reasons = getattr(payload, "reasons", ()) or ()
        reason = reasons[0] if reasons else "scanner blocked without explicit reason"
        rejection_counts[f"scanner: {reason}"] += 1

    def _register_scanner_state(self, *, scanner_state_counts: dict[str, int], payload) -> None:
        if payload is None:
            return
        state = getattr(payload, "state", None)
        if state is None:
            return
        scanner_state_counts[str(getattr(state, "value", state))] += 1

    def _register_health_rejection(self, *, rejection_counts: dict[str, int], payload) -> None:
        if not isinstance(payload, dict):
            return
        stage = str(payload.get("stage", "")).strip()
        message = str(payload.get("message", "")).strip()
        if not stage or not message:
            return
        if stage not in {"strategy_block", "daily_guard", "entry_validation", "gap_guard", "portfolio_guard"}:
            return
        rejection_counts[f"{stage}: {message}"] += 1

    def _register_signal_acceptance(
        self,
        *,
        accepted_signal_counts: dict[str, int],
        accepted_quality_counts: dict[str, int],
        accepted_session_counts: dict[str, int],
        accepted_market_state_counts: dict[str, int],
        payload,
    ) -> None:
        if payload is None:
            return
        metadata = getattr(payload, "metadata", {}) or {}
        execution_band = str(metadata.get("setup_execution_band", "unknown"))
        quality_label = str(metadata.get("setup_quality_label", "unknown"))
        session_name = str(metadata.get("session_name", "unknown"))
        market_state = str(metadata.get("market_state", "unknown"))
        accepted_signal_counts[execution_band] += 1
        accepted_quality_counts[quality_label] += 1
        accepted_session_counts[session_name] += 1
        accepted_market_state_counts[market_state] += 1

    def _top_rejections(self, rejection_counts: dict[str, int], limit: int = 3) -> list[tuple[str, int]]:
        return sorted(
            rejection_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:limit]

    def _sorted_counts(self, counts: dict[str, int]) -> list[dict[str, object]]:
        return [
            {"label": label, "count": count}
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _format_duration(self, seconds: float | None) -> str:
        if seconds is None:
            return "--"
        remaining = max(0, int(round(seconds)))
        hours, remainder = divmod(remaining, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m {secs:02d}s"
        if minutes > 0:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _build_diagnostics_payload(
        self,
        *,
        symbol: str,
        execution_timeframe: str,
        start_date: str,
        end_date: str,
        runtime,
        total_steps: int,
        steps_processed: int,
        scanner_state_counts: dict[str, int],
        accepted_signal_counts: dict[str, int],
        accepted_quality_counts: dict[str, int],
        accepted_session_counts: dict[str, int],
        accepted_market_state_counts: dict[str, int],
        rejection_counts: dict[str, int],
        gap_windows: int,
        gap_blocked_steps: int,
        gap_forced_exits: int,
        daily_rows: list[dict[str, object]],
    ) -> dict[str, object]:
        trade_days = len(daily_rows)
        calendar_days = max(
            1,
            (
                self._parse_history_timestamp(end_date).astimezone(ZoneInfo(self.config.system.sessions.timezone)).date()
                - self._parse_history_timestamp(start_date).astimezone(ZoneInfo(self.config.system.sessions.timezone)).date()
            ).days,
        )
        daily_trade_counts = [int(row["closed_trades"]) for row in daily_rows]
        daily_r_values = [float(row["realized_r"]) for row in daily_rows]
        good_day_threshold = self.config.risk.risk.good_day_threshold_r
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "execution_timeframe": execution_timeframe,
            "start_date": start_date,
            "end_date": end_date,
            "steps_processed": steps_processed,
            "total_steps": total_steps,
            "progress_pct": 0.0 if total_steps == 0 else steps_processed / total_steps,
            "closed_trades": len(runtime.portfolio_manager.closed_trades),
            "current_equity": runtime.portfolio_manager.current_equity,
            "realized_pnl": runtime.portfolio_manager.realized_pnl,
            "gap_windows": gap_windows,
            "gap_blocked_steps": gap_blocked_steps,
            "gap_forced_exits": gap_forced_exits,
            "scanner_state_counts": self._sorted_counts(scanner_state_counts),
            "accepted_signal_bands": self._sorted_counts(accepted_signal_counts),
            "accepted_quality_labels": self._sorted_counts(accepted_quality_counts),
            "accepted_sessions": self._sorted_counts(accepted_session_counts),
            "accepted_market_states": self._sorted_counts(accepted_market_state_counts),
            "rejection_counts": self._sorted_counts(rejection_counts),
            "cadence": {
                "calendar_days_in_range": calendar_days,
                "trade_days": trade_days,
                "avg_trades_per_calendar_day": (
                    0.0
                    if calendar_days == 0
                    else len(runtime.portfolio_manager.closed_trades) / calendar_days
                ),
                "avg_trades_per_trade_day": (
                    0.0
                    if trade_days == 0
                    else len(runtime.portfolio_manager.closed_trades) / trade_days
                ),
                "median_trades_per_trade_day": 0.0 if not daily_trade_counts else median(daily_trade_counts),
                "max_trades_in_one_day": 0 if not daily_trade_counts else max(daily_trade_counts),
                "days_with_8_to_12_trades": sum(
                    1 for count in daily_trade_counts if 8 <= count <= 12
                ),
                "days_with_at_least_8_trades": sum(1 for count in daily_trade_counts if count >= 8),
                "days_hitting_good_day_threshold_r": sum(
                    1 for value in daily_r_values if value >= good_day_threshold
                ),
                "avg_realized_r_per_trade_day": (
                    0.0 if not daily_r_values else sum(daily_r_values) / len(daily_r_values)
                ),
            },
        }

    def _resume_signature(self, *, symbols: tuple[str, ...], execution_timeframe: str) -> dict[str, object]:
        profile = self.config.strategy.resolve_profile(execution_timeframe)
        return {
            "mode": "backtest",
            "symbols": list(symbols),
            "symbol_scope": self._symbol_scope_label(symbols),
            "execution_timeframe": execution_timeframe,
            "clock_timeframe": profile.clock_timeframe,
            "trigger_timeframe": profile.trigger_timeframe,
            "base_timeframe": self.config.system.market.base_timeframe,
            "starting_equity": float(self.config.system.account.initial_equity),
            "profile_name": profile.name,
            "profile_scanner": asdict(profile.scanner),
            "profile_trigger": asdict(profile.trigger),
            "quality_filter": asdict(self.config.strategy.filters.quality),
            "context_filter": asdict(self.config.strategy.filters.context),
            "market_state_filter": asdict(self.config.strategy.filters.market_state),
            "session_filter": asdict(self.config.strategy.filters.session),
            "risk_limits": asdict(self.config.risk.risk),
            "session_timezone": self.config.system.sessions.timezone,
            "active_windows": [asdict(window) for window in self.config.system.sessions.active_windows],
            "risk_per_trade": float(self.config.risk.risk.risk_per_trade),
            "gap_aware": bool(self.config.system.backtest.gap_aware),
            "force_flat_before_gap": bool(self.config.system.backtest.force_flat_before_gap),
            "post_gap_cooldown_bars": int(self.config.system.backtest.post_gap_cooldown_bars),
        }

    def _checkpoint_compatible(self, *, checkpoint: dict[str, object], resume_signature: dict[str, object]) -> bool:
        checkpoint_signature = checkpoint.get("resume_signature")
        return isinstance(checkpoint_signature, dict) and checkpoint_signature == resume_signature

    def _fast_forward(
        self,
        *,
        replay_engine: MultiAssetReplayEngine,
        runtime,
        selector: SignalSelector,
        gap_policies_by_symbol: dict[str, dict[int, GapStepPolicy]],
        steps: int,
    ) -> tuple[int, int]:
        blocked_steps = 0
        forced_exits = 0
        while replay_engine.has_next() and replay_engine.cursor.processed_steps < steps:
            results, batch_blocked_steps, batch_forced_exits = self._advance_batch(
                replay_engine=replay_engine,
                runtime=runtime,
                selector=selector,
                gap_policies_by_symbol=gap_policies_by_symbol,
                emit_gap_events=False,
            )
            if not results:
                break
            blocked_steps += batch_blocked_steps
            forced_exits += batch_forced_exits
        return blocked_steps, forced_exits

    def _advance_batch(
        self,
        *,
        replay_engine: MultiAssetReplayEngine,
        runtime,
        selector: SignalSelector,
        gap_policies_by_symbol: dict[str, dict[int, GapStepPolicy]],
        emit_gap_events: bool,
    ):
        batch = replay_engine.step_batch()
        if not batch:
            return (), 0, 0

        blocked_steps = 0
        forced_exits = 0
        pending_signals = []
        results: list[tuple[object, tuple[ManagementDecision, ...]]] = []

        for step in batch:
            snapshot = step.snapshot
            policy = gap_policies_by_symbol.get(step.symbol, {}).get(step.execution_index)
            allow_new_entries = policy is None or not policy.block_entries
            if policy is not None:
                blocked_steps += 1
                if emit_gap_events:
                    runtime.event_bus.publish(
                        Event(
                            EventTopic.HEALTH,
                            {
                                "stage": "gap_guard",
                                "symbol": step.symbol,
                                "execution_index": step.execution_index,
                                "gap_ids": policy.gap_ids,
                                "phases": policy.phases,
                                "message": " | ".join(policy.messages),
                            },
                        )
                    )

            management_decisions = runtime.engine.manage_snapshot(snapshot)
            forced_exit = False
            if policy is not None and policy.force_flat and step.execution_just_closed:
                forced_exit = self._force_gap_exit(
                    runtime=runtime,
                    snapshot=snapshot,
                    policy=policy,
                )
            if forced_exit:
                forced_exits += 1

            evaluation = runtime.engine.evaluate_entry_candidate(snapshot, allow_new_entries=allow_new_entries)
            if evaluation.signal is not None:
                pending_signals.append((evaluation, evaluation.signal))
            results.append((evaluation, management_decisions))

        ranked = selector.select(tuple(signal for _, signal in pending_signals))
        selected_by_symbol = {item.signal.symbol: item for item in ranked}

        finalized_results = []
        for evaluation, management_decisions in results:
            risk_plan = None
            selected = selected_by_symbol.get(evaluation.snapshot.symbol)
            if selected is not None:
                risk_plan = runtime.engine.execute_signal(selected.signal, risk_plan=selected.risk_plan)
            finalized_results.append(
                EngineCycleResult(
                    snapshot=evaluation.snapshot,
                    scanner_decision=evaluation.scanner_decision,
                    signal=evaluation.signal,
                    risk_plan=risk_plan,
                    management_decisions=management_decisions,
                    portfolio=runtime.portfolio_manager.snapshot(),
                )
            )
        return tuple(finalized_results), blocked_steps, forced_exits

    def _force_gap_exit(self, *, runtime, snapshot, policy: GapStepPolicy) -> bool:
        position = runtime.portfolio_manager.position_for_symbol(snapshot.symbol)
        latest_candle = snapshot.latest(self.config.system.market.execution_timeframe)
        if position is None or latest_candle is None:
            return False
        gap_label = ",".join(str(gap_id) for gap_id in policy.gap_ids)
        reason = f"gap protection exit before outage #{gap_label}"
        trade = runtime.engine.execution_engine.apply_management(
            position=position,
            decision=ManagementDecision(
                action=ManagementAction.EXIT,
                reason=reason,
                price=latest_candle.close,
            ),
            occurred_at=latest_candle.close_time,
        )
        if trade is None:
            return False
        runtime.portfolio_manager.close_position(trade)
        runtime.event_bus.publish(
            Event(
                EventTopic.HEALTH,
                {
                    "stage": "gap_guard",
                    "gap_ids": policy.gap_ids,
                    "message": reason,
                    "exit_price": latest_candle.close,
                },
            )
        )
        runtime.event_bus.publish(Event(EventTopic.PORTFOLIO_UPDATED, runtime.portfolio_manager.snapshot()))
        return True

    def _build_gap_policy(
        self,
        *,
        symbol: str,
        df_1m,
        execution_series,
        execution_timeframe: str,
    ) -> tuple[tuple[BacktestGapWindow, ...], dict[int, GapStepPolicy]]:
        backtest_cfg = self.config.system.backtest
        if not backtest_cfg.gap_aware or not execution_series:
            return (), {}

        base_timeframe = self.config.system.market.base_timeframe
        base_step = MarketDataDownloader._interval_delta(base_timeframe)
        execution_step = MarketDataDownloader._interval_delta(execution_timeframe)
        index = df_1m.index
        diffs = index.to_series().diff().dropna()
        gap_diffs = diffs[diffs > base_step]
        if gap_diffs.empty:
            return (), {}

        close_times = [candle.close_time for candle in execution_series]
        open_times = [candle.open_time for candle in execution_series]
        windows: list[BacktestGapWindow] = []
        policies: dict[int, GapStepPolicy] = {}

        for gap_id, (next_base_label, delta) in enumerate(gap_diffs.items(), start=1):
            raw_next_base_timestamp = next_base_label.to_pydatetime()
            next_base_timestamp = self._as_utc_datetime(raw_next_base_timestamp)
            previous_base_timestamp = self._as_utc_datetime(
                index[index.get_loc(next_base_label) - 1].to_pydatetime()
            )
            missing_start = previous_base_timestamp + base_step.to_pytimedelta()
            missing_end = next_base_timestamp - base_step.to_pytimedelta()
            missing_minutes = max(0, int(delta / base_step) - 1)

            previous_execution_index = bisect_right(close_times, missing_start) - 1
            if previous_execution_index < 0:
                previous_execution_index = None
            next_execution_index = bisect_left(open_times, next_base_timestamp)
            if next_execution_index >= len(execution_series):
                next_execution_index = None

            previous_execution_close = (
                None
                if previous_execution_index is None
                else execution_series[previous_execution_index].close_time
            )
            next_execution_open = (
                None
                if next_execution_index is None
                else execution_series[next_execution_index].open_time
            )
            next_execution_close = (
                None
                if next_execution_index is None
                else execution_series[next_execution_index].close_time
            )
            missing_execution_bars = 0
            if previous_execution_close is not None and next_execution_close is not None:
                missing_execution_bars = max(
                    0,
                    int((next_execution_close - previous_execution_close) / execution_step) - 1,
                )

            blocked_start_index = previous_execution_index if previous_execution_index is not None else next_execution_index
            blocked_end_index = None
            if next_execution_index is not None:
                blocked_end_index = min(
                    len(execution_series) - 1,
                    next_execution_index + backtest_cfg.post_gap_cooldown_bars,
                )
            elif previous_execution_index is not None:
                blocked_end_index = previous_execution_index

            window = BacktestGapWindow(
                symbol=symbol,
                gap_id=gap_id,
                previous_base_timestamp=previous_base_timestamp,
                next_base_timestamp=next_base_timestamp,
                missing_start=missing_start,
                missing_end=missing_end,
                missing_minutes=missing_minutes,
                previous_execution_index=previous_execution_index,
                previous_execution_close=previous_execution_close,
                next_execution_index=next_execution_index,
                next_execution_open=next_execution_open,
                next_execution_close=next_execution_close,
                missing_execution_bars=missing_execution_bars,
                blocked_entry_start_index=blocked_start_index,
                blocked_entry_end_index=blocked_end_index,
                force_flat_before_gap=backtest_cfg.force_flat_before_gap,
                post_gap_cooldown_bars=backtest_cfg.post_gap_cooldown_bars,
            )
            windows.append(window)

            if previous_execution_index is not None:
                self._register_gap_policy(
                    policies,
                    previous_execution_index,
                    GapStepPolicy(
                        gap_ids=(gap_id,),
                        phases=("pre_gap",),
                        block_entries=True,
                        force_flat=backtest_cfg.force_flat_before_gap,
                        messages=(
                            f"blocking new entries before outage #{gap_id} "
                            f"({missing_start} -> {missing_end})",
                        ),
                    ),
                )
            if next_execution_index is not None:
                self._register_gap_policy(
                    policies,
                    next_execution_index,
                    GapStepPolicy(
                        gap_ids=(gap_id,),
                        phases=("post_gap",),
                        block_entries=True,
                        force_flat=False,
                        messages=(
                            f"blocking entries on first execution candle after outage #{gap_id}",
                        ),
                    ),
                )
                for offset in range(1, backtest_cfg.post_gap_cooldown_bars + 1):
                    cooldown_index = next_execution_index + offset
                    if cooldown_index >= len(execution_series):
                        break
                    self._register_gap_policy(
                        policies,
                        cooldown_index,
                        GapStepPolicy(
                            gap_ids=(gap_id,),
                            phases=("post_gap_cooldown",),
                            block_entries=True,
                            force_flat=False,
                            messages=(
                                f"blocking entries during post-gap cooldown after outage #{gap_id}",
                            ),
                        ),
                    )

        self._log(
            f"Gap-aware backtest activated for {len(windows)} outage window(s).",
            level="warning",
        )
        return tuple(windows), policies

    def _as_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _register_gap_policy(
        self,
        policies: dict[int, GapStepPolicy],
        index: int,
        policy: GapStepPolicy,
    ) -> None:
        existing = policies.get(index)
        if existing is None:
            policies[index] = policy
            return
        policies[index] = GapStepPolicy(
            gap_ids=tuple(dict.fromkeys(existing.gap_ids + policy.gap_ids)),
            phases=tuple(dict.fromkeys(existing.phases + policy.phases)),
            block_entries=existing.block_entries or policy.block_entries,
            force_flat=existing.force_flat or policy.force_flat,
            messages=tuple(dict.fromkeys(existing.messages + policy.messages)),
        )
