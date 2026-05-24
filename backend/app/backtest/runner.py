"""Checkpointed backtest runner built on top of the replay engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config.models import ConfigBundle
from backend.app.core import JsonCheckpointStore
from backend.app.core.orchestrator import build_runtime
from backend.app.data import MarketDataDownloader, TimeframeBuilder, dataframe_to_candles
from backend.app.replay import ReplayEngine, ReplaySimulator

from .csv_logger import EquityCsvLogger, TradeCsvLogger


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

        backtest_cfg = self.config.system.backtest
        output_dir = Path(backtest_cfg.output_dir)
        checkpoint_path = (
            output_dir
            / backtest_cfg.checkpoint_dir
            / f"{symbol}_{execution_timeframe}_{start_date}_to_{end_date}{backtest_cfg.checkpoint_suffix}"
        )
        checkpoint_store = JsonCheckpointStore(checkpoint_path)
        trade_logger = TradeCsvLogger(output_dir / "trades.csv")
        equity_logger = EquityCsvLogger(output_dir / "equity.csv")

        checkpoint = checkpoint_store.read() if backtest_cfg.resume_enabled else None
        resume = bool(checkpoint and not checkpoint.get("completed", False))
        trade_logger.initialize(resume=resume)
        equity_logger.initialize(resume=resume)

        resume_index = int(checkpoint.get("next_index", 0)) if resume and checkpoint else 0
        if resume_index > 0:
            self._log(f"Resuming backtest from checkpoint index {resume_index}", level="warning")
            self._fast_forward(simulator, resume_index)

        save_every = max(1, backtest_cfg.save_every_steps)
        total_steps = len(candles_by_timeframe.get(execution_timeframe, ()))
        update_stride = max(1, total_steps // 300) if total_steps else 1
        while replay_engine.has_next():
            closed_before = len(runtime.portfolio_manager.closed_trades)
            result = simulator.step()
            if result is None:
                break
            closed_after = len(runtime.portfolio_manager.closed_trades)
            if closed_after > closed_before:
                for trade in runtime.portfolio_manager.closed_trades[closed_before:closed_after]:
                    trade_logger.append(trade)
            equity_logger.append(
                timestamp=result.snapshot.generated_at.isoformat(),
                equity=result.portfolio.current_equity,
            )
            if (
                replay_engine.cursor.index % update_stride == 0
                or replay_engine.cursor.index == total_steps
            ):
                self._emit(
                    "progress",
                    description=f"Backtesting {symbol} {execution_timeframe}",
                    completed=replay_engine.cursor.index,
                    total=total_steps,
                    status="running",
                )
                self._emit(
                    "metrics",
                    metrics={
                        "symbol": symbol,
                        "range": f"{start_date} -> {end_date}",
                        "steps": replay_engine.cursor.index,
                        "closed_trades": len(runtime.portfolio_manager.closed_trades),
                        "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                        "realized_pnl": f"{runtime.portfolio_manager.realized_pnl:.2f}",
                    },
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
        )

    def _fast_forward(self, simulator: ReplaySimulator, steps: int) -> None:
        for _ in range(steps):
            result = simulator.step()
            if result is None:
                break
