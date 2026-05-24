"""Checkpoint-aware replay runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config.models import ConfigBundle, history_path_label
from backend.app.core import JsonCheckpointStore
from backend.app.core.orchestrator import build_runtime
from backend.app.data import MarketDataDownloader, TimeframeBuilder, dataframe_to_candles

from .replay_engine import ReplayEngine
from .simulator import ReplaySimulator


@dataclass(frozen=True)
class ReplayRunSummary:
    """High-level replay execution summary."""

    symbol: str
    execution_timeframe: str
    steps_processed: int
    current_index: int
    closed_trades: int
    current_equity: float
    checkpoint_path: Path


class ReplayRunner:
    """Run replay in checkpointed chunks for inspection or operator training."""

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
        max_steps: int | None = None,
    ) -> ReplayRunSummary:
        symbol = (symbol or self.config.system.market.symbol).upper()
        start_date = start_date or self.config.system.history.start_date
        end_date = end_date or self.config.system.history.end_date
        execution_timeframe = self.config.system.market.execution_timeframe
        self._emit(
            "phase",
            status="running",
            phase="preparing replay run",
            detail=f"{symbol} | {start_date} -> {end_date}",
        )

        history_path = (
            self.config.system.storage.root
            / symbol
            / self.config.system.market.base_timeframe
            / (
                f"{symbol}_{self.config.system.market.base_timeframe}_{history_path_label(start_date)}"
                f"_to_{history_path_label(end_date)}.csv"
            )
        )
        if history_path.exists():
            df_1m = self.downloader.load_from_csv(history_path)
        else:
            df_1m = self.downloader.fetch_full_history(
                symbol=symbol,
                interval=self.config.system.market.base_timeframe,
                start_date=start_date,
                end_date=end_date,
            )

        frames = self.timeframe_builder.build_timeframes(df_1m)
        candles_by_timeframe = {
            timeframe: dataframe_to_candles(frame, symbol=symbol, timeframe=timeframe)
            for timeframe, frame in frames.items()
        }

        runtime = build_runtime(self.config)
        replay_engine = ReplayEngine(
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            candles_by_timeframe=candles_by_timeframe,
        )
        simulator = ReplaySimulator(replay_engine, runtime.engine)

        replay_cfg = self.config.system.replay
        output_dir = Path(replay_cfg.output_dir)
        checkpoint_path = (
            output_dir
            / replay_cfg.checkpoint_dir
            / (
                f"{symbol}_{execution_timeframe}_{history_path_label(start_date)}"
                f"_to_{history_path_label(end_date)}{replay_cfg.checkpoint_suffix}"
            )
        )
        checkpoint_store = JsonCheckpointStore(checkpoint_path)
        checkpoint = checkpoint_store.read() if replay_cfg.resume_enabled else None
        resume_signature = self._resume_signature(symbol=symbol, execution_timeframe=execution_timeframe)
        if checkpoint and not self._checkpoint_compatible(checkpoint=checkpoint, resume_signature=resume_signature):
            self._log("Ignoring incompatible replay checkpoint and starting fresh state.", level="warning")
            checkpoint = None
        resume_index = 0
        if checkpoint and not checkpoint.get("completed", False):
            resume_index = int(checkpoint.get("next_index", 0))
        if resume_index > 0:
            self._log(f"Resuming replay from checkpoint index {resume_index}", level="warning")
            for _ in range(resume_index):
                result = simulator.step()
                if result is None:
                    break

        steps_this_run = 0
        save_every = max(1, replay_cfg.save_every_steps)
        total_steps = len(candles_by_timeframe.get(execution_timeframe, ()))
        update_stride = max(1, total_steps // 250) if total_steps else 1
        while replay_engine.has_next():
            if max_steps is not None and steps_this_run >= max_steps:
                break
            result = simulator.step()
            if result is None:
                break
            steps_this_run += 1
            if (
                replay_engine.cursor.index % update_stride == 0
                or replay_engine.cursor.index == total_steps
            ):
                self._emit(
                    "progress",
                    description=f"Replay stepping {symbol} {execution_timeframe}",
                    completed=replay_engine.cursor.index,
                    total=total_steps,
                    status="running",
                )
                self._emit(
                    "metrics",
                    metrics={
                        "symbol": symbol,
                        "range": f"{start_date} -> {end_date}",
                        "steps_this_run": steps_this_run,
                        "current_index": replay_engine.cursor.index,
                        "closed_trades": len(runtime.portfolio_manager.closed_trades),
                        "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                    },
                )
            if replay_cfg.enabled and replay_engine.cursor.index % save_every == 0:
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

        completed = not replay_engine.has_next()
        self._emit(
            "complete",
            status="completed" if completed else "running",
            phase="replay run complete",
            detail=str(checkpoint_path),
            metrics={
                "steps_this_run": steps_this_run,
                "current_index": replay_engine.cursor.index,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
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
                "completed": completed,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return ReplayRunSummary(
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            steps_processed=steps_this_run,
            current_index=replay_engine.cursor.index,
            closed_trades=len(runtime.portfolio_manager.closed_trades),
            current_equity=runtime.portfolio_manager.current_equity,
            checkpoint_path=checkpoint_path,
        )

    def _resume_signature(self, *, symbol: str, execution_timeframe: str) -> dict[str, object]:
        profile = self.config.strategy.resolve_profile(execution_timeframe)
        return {
            "mode": "replay",
            "symbol": symbol,
            "execution_timeframe": execution_timeframe,
            "base_timeframe": self.config.system.market.base_timeframe,
            "starting_equity": float(self.config.system.account.initial_equity),
            "profile_name": profile.name,
            "risk_per_trade": float(self.config.risk.risk.risk_per_trade),
        }

    def _checkpoint_compatible(self, *, checkpoint: dict[str, object], resume_signature: dict[str, object]) -> bool:
        checkpoint_signature = checkpoint.get("resume_signature")
        return isinstance(checkpoint_signature, dict) and checkpoint_signature == resume_signature
