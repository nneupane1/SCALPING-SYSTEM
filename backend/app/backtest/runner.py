"""Checkpointed backtest runner built on top of the replay engine."""

from __future__ import annotations

from collections import defaultdict
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from backend.app.config.models import ConfigBundle, history_path_label
from backend.app.core import JsonCheckpointStore
from backend.app.core.events import Event, EventTopic
from backend.app.core.models import ManagementAction, ManagementDecision
from backend.app.core.orchestrator import build_runtime
from backend.app.data import MarketDataDownloader, TimeframeBuilder, dataframe_to_candles
from backend.app.replay import ReplayEngine

from .csv_logger import EquityCsvLogger, GapCsvLogger, TradeCsvLogger


@dataclass(frozen=True)
class BacktestGapWindow:
    """One detected historical outage window mapped into execution-candle space."""

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
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> BacktestSummary:
        symbol = (symbol or self.config.system.market.symbol).upper()
        start_date = start_date or self.config.system.history.start_date
        end_date = end_date or self.config.system.history.end_date
        execution_timeframe = self.config.system.market.execution_timeframe
        self._emit(
            "phase",
            status="running",
            phase="preparing backtest",
            detail=f"{symbol} | {start_date} -> {end_date}",
        )

        df_1m = self.downloader.fetch_full_history(
            symbol=symbol,
            interval=self.config.system.market.base_timeframe,
            start_date=start_date,
            end_date=end_date,
        )
        frames = self.timeframe_builder.build_timeframes_and_save(
            df_1m,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        candles_by_timeframe = {
            timeframe: dataframe_to_candles(
                frame,
                symbol=symbol,
                timeframe=timeframe,
                index_is_close_time=(timeframe != self.config.system.market.base_timeframe),
            )
            for timeframe, frame in frames.items()
        }
        execution_series = candles_by_timeframe.get(execution_timeframe, ())
        gap_windows, gap_policies = self._build_gap_policy(
            df_1m=df_1m,
            execution_series=execution_series,
            execution_timeframe=execution_timeframe,
        )

        runtime = build_runtime(self.config)
        rejection_counts: dict[str, int] = defaultdict(int)
        runtime.event_bus.subscribe(
            EventTopic.SCANNER_UPDATED,
            lambda event: self._register_scanner_rejection(
                rejection_counts=rejection_counts,
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
        replay_engine = ReplayEngine(
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            candles_by_timeframe=candles_by_timeframe,
        )

        backtest_cfg = self.config.system.backtest
        output_dir = Path(backtest_cfg.output_dir)
        checkpoint_path = (
            output_dir
            / backtest_cfg.checkpoint_dir
            / (
                f"{symbol}_{execution_timeframe}_{history_path_label(start_date)}"
                f"_to_{history_path_label(end_date)}{backtest_cfg.checkpoint_suffix}"
            )
        )
        checkpoint_store = JsonCheckpointStore(checkpoint_path)
        trade_logger = TradeCsvLogger(output_dir / "trades.csv")
        equity_logger = EquityCsvLogger(output_dir / "equity.csv")
        gap_logger = GapCsvLogger(output_dir / "gap_windows.csv")

        checkpoint = checkpoint_store.read() if backtest_cfg.resume_enabled else None
        resume_signature = self._resume_signature(symbol=symbol, execution_timeframe=execution_timeframe)
        if checkpoint and not self._checkpoint_compatible(checkpoint=checkpoint, resume_signature=resume_signature):
            self._log("Ignoring incompatible backtest checkpoint and starting fresh state.", level="warning")
            checkpoint = None
        resume = bool(checkpoint and not checkpoint.get("completed", False))
        trade_logger.initialize(resume=resume)
        equity_logger.initialize(resume=resume)
        if backtest_cfg.output_gap_windows:
            gap_logger.initialize(resume=resume)
            if not (resume and gap_logger.path.exists()):
                gap_logger.write_all(gap_windows)

        resume_index = int(checkpoint.get("next_index", 0)) if resume and checkpoint else 0
        gap_blocked_steps = 0
        gap_forced_exits = 0
        if resume_index > 0:
            self._log(f"Resuming backtest from checkpoint index {resume_index}", level="warning")
            gap_blocked_steps, gap_forced_exits = self._fast_forward(
                replay_engine=replay_engine,
                runtime=runtime,
                gap_policies=gap_policies,
                steps=resume_index,
            )

        save_every = max(1, backtest_cfg.save_every_steps)
        total_steps = len(execution_series)
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
                f"{symbol} {execution_timeframe} | "
                f"{total_steps:,} execution candles | "
                f"starting at step {resume_index:,}"
            ),
        )
        self._emit(
            "progress",
            description=f"Backtesting {symbol} {execution_timeframe}",
            completed=resume_index,
            total=total_steps,
            status="running",
        )
        self._emit(
            "metrics",
            metrics=self._build_runtime_metrics(
                symbol=symbol,
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
                gap_windows=len(gap_windows),
                gap_blocked_steps=gap_blocked_steps,
                gap_forced_exits=gap_forced_exits,
                rejection_counts=rejection_counts,
            ),
        )
        while replay_engine.has_next():
            closed_before = len(runtime.portfolio_manager.closed_trades)
            result, policy, forced_exit = self._advance_one_step(
                replay_engine=replay_engine,
                runtime=runtime,
                gap_policies=gap_policies,
                emit_gap_events=True,
            )
            if result is None:
                break
            if policy is not None:
                gap_blocked_steps += 1
            if forced_exit:
                gap_forced_exits += 1
            closed_after = len(runtime.portfolio_manager.closed_trades)
            if closed_after > closed_before:
                for trade in runtime.portfolio_manager.closed_trades[closed_before:closed_after]:
                    trade_logger.append(trade)
            equity_logger.append(
                timestamp=result.snapshot.generated_at.isoformat(),
                equity=runtime.portfolio_manager.current_equity,
            )
            now = perf_counter()
            should_refresh = (
                replay_engine.cursor.index % update_stride == 0
                or replay_engine.cursor.index == total_steps
                or closed_after > closed_before
                or now - last_ui_update_at >= 1.0
            )
            if should_refresh:
                elapsed_seconds = max(1e-9, now - loop_started_at)
                processed_since_loop_start = max(0, replay_engine.cursor.index - resume_index)
                steps_per_second = processed_since_loop_start / elapsed_seconds
                remaining_steps = max(0, total_steps - replay_engine.cursor.index)
                eta_seconds = (
                    remaining_steps / steps_per_second
                    if steps_per_second > 0
                    else None
                )
                simulated_at = result.snapshot.generated_at
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
                    description=f"Backtesting {symbol} {execution_timeframe}",
                    completed=replay_engine.cursor.index,
                    total=total_steps,
                    status="running",
                )
                self._emit(
                    "phase",
                    status="running",
                    phase="running backtest",
                    detail=(
                        f"{symbol} {execution_timeframe} | "
                        f"simulated {simulated_at.isoformat()} | "
                        f"step {replay_engine.cursor.index:,} / {total_steps:,}"
                    ),
                )
                self._emit(
                    "metrics",
                    metrics=self._build_runtime_metrics(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        total_steps=total_steps,
                        steps_done=replay_engine.cursor.index,
                        simulated_at=simulated_at,
                        simulated_progress=simulated_progress,
                        steps_per_second=steps_per_second,
                        eta_seconds=eta_seconds,
                        runtime=runtime,
                        latest_trade=latest_trade,
                        gap_windows=len(gap_windows),
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
            if backtest_cfg.enabled and replay_engine.cursor.index % save_every == 0:
                checkpoint_store.write(
                    {
                        "symbol": symbol,
                        "execution_timeframe": execution_timeframe,
                        "start_date": start_date,
                        "end_date": end_date,
                        "next_index": replay_engine.cursor.index,
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
                "steps": replay_engine.cursor.index,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                "realized_pnl": f"{runtime.portfolio_manager.realized_pnl:.2f}",
                "gap_windows": len(gap_windows),
                "gap_blocked_steps": gap_blocked_steps,
                "gap_forced_exits": gap_forced_exits,
            },
        )
        checkpoint_store.write(
            {
                "symbol": symbol,
                "execution_timeframe": execution_timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "next_index": replay_engine.cursor.index,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": runtime.portfolio_manager.current_equity,
                "resume_signature": resume_signature,
                "completed": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        return BacktestSummary(
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            start_date=start_date,
            end_date=end_date,
            steps_processed=replay_engine.cursor.index,
            closed_trades=len(runtime.portfolio_manager.closed_trades),
            current_equity=runtime.portfolio_manager.current_equity,
            realized_pnl=runtime.portfolio_manager.realized_pnl,
            output_dir=output_dir,
            gap_windows=len(gap_windows),
            gap_blocked_steps=gap_blocked_steps,
            gap_forced_exits=gap_forced_exits,
        )

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

    def _register_health_rejection(self, *, rejection_counts: dict[str, int], payload) -> None:
        if not isinstance(payload, dict):
            return
        stage = str(payload.get("stage", "")).strip()
        message = str(payload.get("message", "")).strip()
        if not stage or not message:
            return
        if stage not in {"strategy_block", "daily_guard", "entry_validation", "gap_guard"}:
            return
        rejection_counts[f"{stage}: {message}"] += 1

    def _top_rejections(self, rejection_counts: dict[str, int], limit: int = 3) -> list[tuple[str, int]]:
        return sorted(
            rejection_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:limit]

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

    def _resume_signature(self, *, symbol: str, execution_timeframe: str) -> dict[str, object]:
        profile = self.config.strategy.resolve_profile(execution_timeframe)
        return {
            "mode": "backtest",
            "symbol": symbol,
            "execution_timeframe": execution_timeframe,
            "base_timeframe": self.config.system.market.base_timeframe,
            "starting_equity": float(self.config.system.account.initial_equity),
            "profile_name": profile.name,
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
        replay_engine: ReplayEngine,
        runtime,
        gap_policies: dict[int, GapStepPolicy],
        steps: int,
    ) -> tuple[int, int]:
        blocked_steps = 0
        forced_exits = 0
        for _ in range(steps):
            result, policy, forced_exit = self._advance_one_step(
                replay_engine=replay_engine,
                runtime=runtime,
                gap_policies=gap_policies,
                emit_gap_events=False,
            )
            if result is None:
                break
            if policy is not None:
                blocked_steps += 1
            if forced_exit:
                forced_exits += 1
        return blocked_steps, forced_exits

    def _advance_one_step(
        self,
        *,
        replay_engine: ReplayEngine,
        runtime,
        gap_policies: dict[int, GapStepPolicy],
        emit_gap_events: bool,
    ):
        step_index = replay_engine.cursor.index
        snapshot = replay_engine.step()
        if snapshot is None:
            return None, None, False
        policy = gap_policies.get(step_index)
        allow_new_entries = policy is None or not policy.block_entries
        if policy is not None and emit_gap_events:
            runtime.event_bus.publish(
                Event(
                    EventTopic.HEALTH,
                    {
                        "stage": "gap_guard",
                        "execution_index": step_index,
                        "gap_ids": policy.gap_ids,
                        "phases": policy.phases,
                        "message": " | ".join(policy.messages),
                    },
                )
            )
        result = runtime.engine.process_snapshot(snapshot, allow_new_entries=allow_new_entries)
        forced_exit = False
        if policy is not None and policy.force_flat:
            forced_exit = self._force_gap_exit(
                runtime=runtime,
                snapshot=snapshot,
                policy=policy,
            )
        return result, policy, forced_exit

    def _force_gap_exit(self, *, runtime, snapshot, policy: GapStepPolicy) -> bool:
        position = runtime.portfolio_manager.active_position
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
