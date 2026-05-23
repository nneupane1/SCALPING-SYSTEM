"""Checkpoint-aware replay runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config.models import ConfigBundle
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
    ) -> None:
        self.config = config
        self.downloader = downloader or MarketDataDownloader(config)
        self.timeframe_builder = timeframe_builder or TimeframeBuilder(config)

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

        history_path = (
            self.config.system.storage.root
            / symbol
            / self.config.system.market.base_timeframe
            / f"{symbol}_{self.config.system.market.base_timeframe}_{start_date}_to_{end_date}.csv"
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
            / f"{symbol}_{execution_timeframe}_{start_date}_to_{end_date}{replay_cfg.checkpoint_suffix}"
        )
        checkpoint_store = JsonCheckpointStore(checkpoint_path)
        checkpoint = checkpoint_store.read() if replay_cfg.resume_enabled else None
        resume_index = 0
        if checkpoint and not checkpoint.get("completed", False):
            resume_index = int(checkpoint.get("next_index", 0))
        if resume_index > 0:
            print(f"Resuming replay from checkpoint index {resume_index}")
            for _ in range(resume_index):
                result = simulator.step()
                if result is None:
                    break

        steps_this_run = 0
        save_every = max(1, replay_cfg.save_every_steps)
        while replay_engine.has_next():
            if max_steps is not None and steps_this_run >= max_steps:
                break
            result = simulator.step()
            if result is None:
                break
            steps_this_run += 1
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
                        "completed": False,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        completed = not replay_engine.has_next()
        checkpoint_store.write(
            {
                "symbol": symbol,
                "execution_timeframe": execution_timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "next_index": replay_engine.cursor.index,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": runtime.portfolio_manager.current_equity,
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
