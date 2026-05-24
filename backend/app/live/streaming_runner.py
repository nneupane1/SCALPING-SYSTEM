"""Websocket-driven live runner over closed Binance 1m candles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.app.api.websocket import WebSocketBroadcaster
from backend.app.backtest.csv_logger import EquityCsvLogger, TradeCsvLogger
from backend.app.config.models import ConfigBundle
from backend.app.core import JsonCheckpointStore
from backend.app.core.orchestrator import build_runtime
from backend.app.data import (
    BinanceMarketStreamClient,
    BinanceStreamRequest,
    MarketDataDownloader,
    TimeframeBuilder,
    dataframe_to_candles,
)
from backend.app.execution import BinanceBroker, BinanceUserDataStreamClient

from .runner import ForwardRunner


@dataclass(frozen=True)
class LiveStreamRunSummary:
    """Summary returned by the websocket-driven live runner."""

    symbol: str
    execution_timeframe: str
    market_events_processed: int
    snapshots_processed: int
    latest_execution_close: datetime | None
    closed_trades: int
    current_equity: float
    checkpoint_path: Path
    live_orders_enabled: bool


class StreamingLiveRunner(ForwardRunner):
    """Consume closed 1m websocket candles and drive the engine in real time."""

    def __init__(
        self,
        config: ConfigBundle,
        *,
        broadcaster: WebSocketBroadcaster | None = None,
        downloader: MarketDataDownloader | None = None,
        timeframe_builder: TimeframeBuilder | None = None,
        progress_callback=None,
    ) -> None:
        super().__init__(
            config,
            mode="live",
            broadcaster=broadcaster,
            downloader=downloader,
            timeframe_builder=timeframe_builder,
            progress_callback=progress_callback,
        )

    def run(
        self,
        *,
        symbol: str | None = None,
        max_events: int | None = None,
    ) -> LiveStreamRunSummary:
        symbol = (symbol or self.config.system.market.symbol).upper()
        execution_timeframe = self.config.system.market.execution_timeframe
        forward_cfg = self._mode_config()
        runtime = build_runtime(self.config)
        self._emit(
            "phase",
            status="running",
            phase="starting websocket live runner",
            detail=f"{symbol} | {execution_timeframe}",
        )
        self._emit(
            "context",
            context={
                "mode": "live",
                "execution_tf": execution_timeframe,
                "context_tf": ", ".join(self.config.system.market.context_timeframes) or "none",
                "market_stream": f"{symbol.lower()}@kline_{self.config.system.market.base_timeframe}",
                "live_orders_enabled": self.config.risk.execution.allow_live_orders,
            },
        )

        output_dir = Path(forward_cfg.output_dir)
        checkpoint_path = (
            output_dir
            / forward_cfg.checkpoint_dir
            / f"{symbol}_{execution_timeframe}_live_stream{forward_cfg.checkpoint_suffix}"
        )
        checkpoint_store = JsonCheckpointStore(checkpoint_path)
        checkpoint = checkpoint_store.read() if forward_cfg.resume_enabled else None
        resume_signature = self._resume_signature(symbol=symbol, execution_timeframe=execution_timeframe)
        if checkpoint and not self._checkpoint_compatible(checkpoint=checkpoint, resume_signature=resume_signature):
            self._log("Ignoring incompatible live stream checkpoint and starting fresh state.", level="warning")
            checkpoint = None
        if checkpoint:
            latest_seen = checkpoint.get("latest_execution_close")
            if latest_seen:
                self._log(f"Resuming live stream runner from checkpoint close {latest_seen}", level="warning")
            self._restore_runtime_state(runtime, checkpoint)

        trade_logger = TradeCsvLogger(output_dir / "trades.csv")
        equity_logger = EquityCsvLogger(output_dir / "equity.csv")
        resume_logs = bool(checkpoint and forward_cfg.resume_enabled)
        trade_logger.initialize(resume=resume_logs)
        equity_logger.initialize(resume=resume_logs)

        base_df = self._bootstrap_base_history(symbol=symbol, forward_cfg=forward_cfg)
        runtime_history_path = self.downloader.realtime_runtime_path(
            symbol=symbol,
            interval=self.config.system.market.base_timeframe,
        )
        last_realtime_persisted_at = self.downloader.latest_timestamp_in_csv(runtime_history_path)
        last_realtime_persisted_at = self.downloader.append_realtime_history(
            symbol=symbol,
            interval=self.config.system.market.base_timeframe,
            frame=base_df,
            last_persisted_at=last_realtime_persisted_at,
        )
        try:
            recent_df = self.downloader.fetch_recent(
                symbol=symbol,
                interval=self.config.system.market.base_timeframe,
                limit=forward_cfg.recent_limit,
                verbose=False,
            )
            last_realtime_persisted_at = self.downloader.append_realtime_history(
                symbol=symbol,
                interval=self.config.system.market.base_timeframe,
                frame=recent_df,
                last_persisted_at=last_realtime_persisted_at,
            )
            base_df = self._merge_recent_history(
                base_df=base_df,
                recent_df=recent_df,
                warmup_limit=forward_cfg.warmup_base_candles,
            )
        except Exception as exc:
            self._log(f"Recent REST bootstrap skipped: {exc}", level="warning")

        latest_execution_close = self._parse_timestamp(checkpoint.get("latest_execution_close")) if checkpoint else None
        if latest_execution_close is None:
            latest_execution_close = self._latest_execution_close_from_base(base_df)

        market_stream = BinanceMarketStreamClient(
            config=self.config,
            requests=(BinanceStreamRequest(symbol=symbol, channel=f"kline_{self.config.system.market.base_timeframe}"),),
            on_event=self._handle_stream_event,
        )
        user_stream = self._build_user_stream(runtime)

        events_processed = 0
        snapshots_processed = 0
        market_stream.start()
        if user_stream is not None:
            user_stream.start()
        self._emit(
            "event",
            level="success",
            message="Live market websocket started.",
        )

        try:
            while max_events is None or events_processed < max_events:
                event = market_stream.wait_for_closed_kline(
                    timeout_seconds=self.config.system.binance.stream_inactivity_timeout_seconds
                )
                if event is None:
                    self._emit(
                        "event",
                        level="warning",
                        message="No closed 1m websocket candle received within inactivity timeout.",
                    )
                    self._write_checkpoint(
                        checkpoint_store=checkpoint_store,
                        symbol=symbol,
                        execution_timeframe=execution_timeframe,
                        latest_execution_close=latest_execution_close,
                        runtime=runtime,
                        polls_processed=events_processed,
                        snapshots_processed=snapshots_processed,
                        completed=False,
                    )
                    continue

                events_processed += 1
                self._emit(
                    "progress",
                    description=f"Streaming closed 1m candles for {symbol}",
                    completed=events_processed,
                    total=max_events,
                    status="running",
                )
                self._emit(
                    "metrics",
                    metrics={
                        "market_events": events_processed,
                        "snapshots": snapshots_processed,
                        "closed_trades": len(runtime.portfolio_manager.closed_trades),
                        "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                        "last_1m_close": event.close_time,
                    },
                )

                event_frame = event.to_frame()
                base_df = self._merge_recent_history(
                    base_df=base_df,
                    recent_df=event_frame,
                    warmup_limit=forward_cfg.warmup_base_candles,
                )
                last_realtime_persisted_at = self.downloader.append_realtime_history(
                    symbol=symbol,
                    interval=self.config.system.market.base_timeframe,
                    frame=event_frame,
                    last_persisted_at=last_realtime_persisted_at,
                )
                frames = self.timeframe_builder.build_timeframes(base_df)
                candles_by_timeframe = {
                    timeframe: dataframe_to_candles(frame, symbol=symbol, timeframe=timeframe)
                    for timeframe, frame in frames.items()
                }
                execution_series = candles_by_timeframe.get(execution_timeframe, ())
                new_candles = tuple(
                    candle
                    for candle in execution_series
                    if latest_execution_close is None or candle.close_time > latest_execution_close
                )
                if not new_candles:
                    if events_processed % max(1, forward_cfg.save_every_polls) == 0:
                        self._write_checkpoint(
                            checkpoint_store=checkpoint_store,
                            symbol=symbol,
                            execution_timeframe=execution_timeframe,
                            latest_execution_close=latest_execution_close,
                            runtime=runtime,
                            polls_processed=events_processed,
                            snapshots_processed=snapshots_processed,
                            resume_signature=resume_signature,
                            completed=False,
                        )
                    continue

                for execution_candle in new_candles:
                    snapshot = self._snapshot_for_candle(
                        symbol=symbol,
                        execution_close=execution_candle.close_time,
                        candles_by_timeframe=candles_by_timeframe,
                    )
                    closed_before = len(runtime.portfolio_manager.closed_trades)
                    result = runtime.engine.process_snapshot(snapshot)
                    if self.broadcaster is not None:
                        self.broadcaster.publish("engine.cycle", result)
                    closed_after = len(runtime.portfolio_manager.closed_trades)
                    if closed_after > closed_before:
                        for trade in runtime.portfolio_manager.closed_trades[closed_before:closed_after]:
                            trade_logger.append(trade)
                            self._log(
                                f"Closed {trade.side.value} trade | pnl {trade.realized_pnl:.2f} | r {trade.realized_r:.2f}",
                                level="success",
                            )
                    equity_logger.append(
                        timestamp=result.snapshot.generated_at.isoformat(),
                        equity=result.portfolio.current_equity,
                    )
                    latest_execution_close = execution_candle.close_time
                    snapshots_processed += 1
                    self._emit(
                        "metrics",
                        metrics={
                            "latest_close": latest_execution_close,
                            "market_events": events_processed,
                            "snapshots": snapshots_processed,
                            "closed_trades": len(runtime.portfolio_manager.closed_trades),
                            "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                        },
                    )

                if events_processed % max(1, forward_cfg.save_every_polls) == 0:
                    self._write_checkpoint(
                        checkpoint_store=checkpoint_store,
                        symbol=symbol,
                        execution_timeframe=execution_timeframe,
                        latest_execution_close=latest_execution_close,
                        runtime=runtime,
                        polls_processed=events_processed,
                        snapshots_processed=snapshots_processed,
                        resume_signature=resume_signature,
                        completed=False,
                    )
        finally:
            market_stream.stop()
            if user_stream is not None:
                user_stream.stop()
            self._write_checkpoint(
                checkpoint_store=checkpoint_store,
                symbol=symbol,
                execution_timeframe=execution_timeframe,
                latest_execution_close=latest_execution_close,
                runtime=runtime,
                polls_processed=events_processed,
                snapshots_processed=snapshots_processed,
                resume_signature=resume_signature,
                completed=False,
            )

        self._emit(
            "complete",
            status="completed",
            phase="websocket live run complete",
            detail=str(checkpoint_path),
            metrics={
                "market_events": events_processed,
                "snapshots": snapshots_processed,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
            },
        )
        return LiveStreamRunSummary(
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            market_events_processed=events_processed,
            snapshots_processed=snapshots_processed,
            latest_execution_close=latest_execution_close,
            closed_trades=len(runtime.portfolio_manager.closed_trades),
            current_equity=runtime.portfolio_manager.current_equity,
            checkpoint_path=checkpoint_path,
            live_orders_enabled=self.config.risk.execution.allow_live_orders,
        )

    def _build_user_stream(self, runtime):
        if not isinstance(runtime.broker, BinanceBroker):
            return None
        api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
        api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
        if not api_key or not api_secret:
            return None
        return BinanceUserDataStreamClient(
            config=self.config,
            api_key=api_key,
            api_secret=api_secret,
            order_manager=runtime.order_manager,
            on_event=self._handle_stream_event,
        )

    def _handle_stream_event(self, event_type: str, payload: object) -> None:
        if event_type.endswith("error"):
            level = "error"
        elif event_type.endswith("closed"):
            level = "warning"
        else:
            level = "info"
        self._emit("event", level=level, message=f"{event_type}: {payload}")
