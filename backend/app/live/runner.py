"""Forward paper/live runner over fresh closed 1m Binance candles."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.api.websocket import WebSocketBroadcaster
from backend.app.backtest.csv_logger import EquityCsvLogger, TradeCsvLogger
from backend.app.config.models import ConfigBundle, ForwardRuntimeConfig
from backend.app.core import ClosedTrade, JsonCheckpointStore, OpenPosition, RiskPlan, Side, TradeSignal
from backend.app.core.models import MarketSnapshot
from backend.app.core.orchestrator import build_runtime
from backend.app.data import MarketDataDownloader, TimeframeBuilder, dataframe_to_candles


@dataclass(frozen=True)
class ForwardRunSummary:
    """Summary returned by one forward-run invocation."""

    mode: str
    symbol: str
    execution_timeframe: str
    polls_processed: int
    snapshots_processed: int
    latest_execution_close: datetime | None
    closed_trades: int
    current_equity: float
    checkpoint_path: Path


class ForwardRunner:
    """Run the trading engine on newly closed execution candles from fresh 1m data."""

    def __init__(
        self,
        config: ConfigBundle,
        *,
        mode: str,
        broadcaster: WebSocketBroadcaster | None = None,
        downloader: MarketDataDownloader | None = None,
        timeframe_builder: TimeframeBuilder | None = None,
        progress_callback=None,
    ) -> None:
        self.config = config
        self.mode = mode.lower()
        self.broadcaster = broadcaster
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
        max_polls: int | None = None,
    ) -> ForwardRunSummary:
        symbol = (symbol or self.config.system.market.symbol).upper()
        execution_timeframe = self.config.system.market.execution_timeframe
        forward_cfg = self._mode_config()
        runtime = build_runtime(self.config)
        self._emit(
            "phase",
            status="running",
            phase=f"starting {self.mode} forward runner",
            detail=f"{symbol} | {execution_timeframe}",
        )
        self._emit(
            "context",
            context={
                "mode": self.mode,
                "execution_tf": execution_timeframe,
                "context_tf": ", ".join(self.config.system.market.context_timeframes) or "none",
                "poll_seconds": forward_cfg.poll_seconds,
            },
        )

        output_dir = Path(forward_cfg.output_dir)
        checkpoint_path = (
            output_dir
            / forward_cfg.checkpoint_dir
            / f"{symbol}_{execution_timeframe}_{self.mode}{forward_cfg.checkpoint_suffix}"
        )
        checkpoint_store = JsonCheckpointStore(checkpoint_path)
        checkpoint = checkpoint_store.read() if forward_cfg.resume_enabled else None
        resume_signature = self._resume_signature(symbol=symbol, execution_timeframe=execution_timeframe)
        if checkpoint and not self._checkpoint_compatible(checkpoint=checkpoint, resume_signature=resume_signature):
            self._log(
                f"Ignoring incompatible {self.mode} checkpoint and starting fresh state.",
                level="warning",
            )
            checkpoint = None
        if checkpoint:
            latest_seen = checkpoint.get("latest_execution_close")
            if latest_seen:
                self._log(f"Resuming {self.mode} runner from checkpoint close {latest_seen}", level="warning")
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
        latest_execution_close = self._parse_timestamp(checkpoint.get("latest_execution_close")) if checkpoint else None
        if latest_execution_close is None:
            latest_execution_close = self._latest_execution_close_from_base(base_df)

        polls_processed = 0
        snapshots_processed = 0
        while max_polls is None or polls_processed < max_polls:
            polls_processed += 1
            self._emit(
                "progress",
                description=f"Polling fresh 1m candles for {symbol}",
                completed=polls_processed,
                total=max_polls,
                status="running",
            )
            self._emit(
                "metrics",
                metrics={
                    "poll": polls_processed,
                    "snapshots": snapshots_processed,
                    "closed_trades": len(runtime.portfolio_manager.closed_trades),
                    "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                },
            )
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
            base_df = self._merge_recent_history(base_df=base_df, recent_df=recent_df, warmup_limit=forward_cfg.warmup_base_candles)
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
                self._log(
                    f"No new closed {execution_timeframe} candle detected on poll {polls_processed}. "
                    "State checkpoint refreshed.",
                    level="info",
                )
                self._write_checkpoint(
                    checkpoint_store=checkpoint_store,
                    symbol=symbol,
                    execution_timeframe=execution_timeframe,
                    latest_execution_close=latest_execution_close,
                    runtime=runtime,
                    polls_processed=polls_processed,
                    snapshots_processed=snapshots_processed,
                    resume_signature=resume_signature,
                    completed=False,
                )
                if max_polls is None or polls_processed < max_polls:
                    time.sleep(forward_cfg.poll_seconds)
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
                        "snapshots": snapshots_processed,
                        "closed_trades": len(runtime.portfolio_manager.closed_trades),
                        "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
                    },
                )
            if forward_cfg.enabled and polls_processed % max(1, forward_cfg.save_every_polls) == 0:
                self._write_checkpoint(
                    checkpoint_store=checkpoint_store,
                    symbol=symbol,
                    execution_timeframe=execution_timeframe,
                    latest_execution_close=latest_execution_close,
                    runtime=runtime,
                    polls_processed=polls_processed,
                    snapshots_processed=snapshots_processed,
                    resume_signature=resume_signature,
                    completed=False,
                )
            if max_polls is not None and polls_processed >= max_polls:
                break
            time.sleep(forward_cfg.poll_seconds)

        self._write_checkpoint(
            checkpoint_store=checkpoint_store,
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            latest_execution_close=latest_execution_close,
            runtime=runtime,
            polls_processed=polls_processed,
            snapshots_processed=snapshots_processed,
            resume_signature=resume_signature,
            completed=False,
        )
        self._emit(
            "complete",
            status="completed",
            phase=f"{self.mode} forward run complete",
            detail=str(checkpoint_path),
            metrics={
                "polls": polls_processed,
                "snapshots": snapshots_processed,
                "closed_trades": len(runtime.portfolio_manager.closed_trades),
                "equity": f"{runtime.portfolio_manager.current_equity:.2f}",
            },
        )
        return ForwardRunSummary(
            mode=self.mode,
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            polls_processed=polls_processed,
            snapshots_processed=snapshots_processed,
            latest_execution_close=latest_execution_close,
            closed_trades=len(runtime.portfolio_manager.closed_trades),
            current_equity=runtime.portfolio_manager.current_equity,
            checkpoint_path=checkpoint_path,
        )

    def _mode_config(self) -> ForwardRuntimeConfig:
        if self.mode == "paper":
            return self.config.system.paper
        if self.mode == "live":
            return self.config.system.live
        raise ValueError(f"Unsupported forward mode: {self.mode}")

    def _bootstrap_base_history(self, *, symbol: str, forward_cfg: ForwardRuntimeConfig) -> pd.DataFrame:
        local_path = self._find_latest_local_base_history(symbol=symbol)
        if local_path is not None:
            df = self.downloader.load_from_csv(local_path)
            return df.tail(forward_cfg.warmup_base_candles)

        self._log("No local 1m history found. Bootstrapping from recent Binance candles only.", level="warning")
        return self.downloader.fetch_recent(
            symbol=symbol,
            interval=self.config.system.market.base_timeframe,
            limit=forward_cfg.recent_limit,
            verbose=False,
        )

    def _find_latest_local_base_history(self, *, symbol: str) -> Path | None:
        folder = self.config.system.storage.root / symbol / self.config.system.market.base_timeframe
        if not folder.exists():
            return None
        candidates = sorted(
            (
                path
                for path in folder.glob(f"{symbol}_{self.config.system.market.base_timeframe}_*.csv")
                if ".partial." not in path.name
            ),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _merge_recent_history(
        self,
        *,
        base_df: pd.DataFrame,
        recent_df: pd.DataFrame,
        warmup_limit: int,
    ) -> pd.DataFrame:
        merged = pd.concat([base_df, recent_df])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        if len(merged) > warmup_limit:
            merged = merged.tail(warmup_limit)
        return merged

    def _latest_execution_close_from_base(self, base_df: pd.DataFrame) -> datetime | None:
        frames = self.timeframe_builder.build_timeframes(base_df)
        execution_frame = frames.get(self.config.system.market.execution_timeframe)
        if execution_frame is None or execution_frame.empty:
            return None
        candles = dataframe_to_candles(
            execution_frame,
            symbol=self.config.system.market.symbol,
            timeframe=self.config.system.market.execution_timeframe,
        )
        if not candles:
            return None
        return candles[-1].close_time

    def _snapshot_for_candle(
        self,
        *,
        symbol: str,
        execution_close: datetime,
        candles_by_timeframe: dict[str, tuple[Any, ...]],
    ) -> MarketSnapshot:
        visible = {
            timeframe: tuple(candle for candle in series if candle.close_time <= execution_close)
            for timeframe, series in candles_by_timeframe.items()
        }
        return MarketSnapshot(symbol=symbol, generated_at=execution_close, candles=visible)

    def _write_checkpoint(
        self,
        *,
        checkpoint_store: JsonCheckpointStore,
        symbol: str,
        execution_timeframe: str,
        latest_execution_close: datetime | None,
        runtime,
        polls_processed: int,
        snapshots_processed: int,
        resume_signature: dict[str, Any],
        completed: bool,
    ) -> None:
        checkpoint_store.write(
            {
                "mode": self.mode,
                "symbol": symbol,
                "execution_timeframe": execution_timeframe,
                "latest_execution_close": (
                    latest_execution_close.isoformat() if latest_execution_close is not None else None
                ),
                "polls_processed": polls_processed,
                "snapshots_processed": snapshots_processed,
                "portfolio": self._serialize_portfolio_state(runtime.portfolio_manager),
                "resume_signature": resume_signature,
                "completed": completed,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _resume_signature(self, *, symbol: str, execution_timeframe: str) -> dict[str, Any]:
        profile = self.config.strategy.resolve_profile(execution_timeframe)
        return {
            "mode": self.mode,
            "symbol": symbol,
            "execution_timeframe": execution_timeframe,
            "base_timeframe": self.config.system.market.base_timeframe,
            "starting_equity": float(self.config.system.account.initial_equity),
            "base_currency": self.config.system.account.base_currency,
            "profile_name": profile.name,
            "risk_per_trade": float(self.config.risk.risk.risk_per_trade),
        }

    def _checkpoint_compatible(
        self,
        *,
        checkpoint: dict[str, Any],
        resume_signature: dict[str, Any],
    ) -> bool:
        checkpoint_signature = checkpoint.get("resume_signature")
        if not isinstance(checkpoint_signature, dict):
            return False
        return checkpoint_signature == resume_signature

    def _restore_runtime_state(self, runtime, checkpoint: dict[str, Any]) -> None:
        payload = checkpoint.get("portfolio")
        if not isinstance(payload, dict):
            return
        portfolio = runtime.portfolio_manager
        portfolio.current_equity = float(payload.get("current_equity", portfolio.current_equity))
        portfolio.realized_pnl = float(payload.get("realized_pnl", portfolio.realized_pnl))
        portfolio.peak_equity = float(payload.get("peak_equity", portfolio.peak_equity))
        portfolio.win_count = int(payload.get("win_count", portfolio.win_count))
        portfolio.loss_count = int(payload.get("loss_count", portfolio.loss_count))
        portfolio.closed_trades = [
            self._deserialize_closed_trade(item)
            for item in payload.get("closed_trades", [])
            if isinstance(item, dict)
        ]
        active_position = payload.get("active_position")
        portfolio.active_position = (
            self._deserialize_open_position(active_position)
            if isinstance(active_position, dict)
            else None
        )

    def _serialize_portfolio_state(self, portfolio_manager) -> dict[str, Any]:
        return {
            "current_equity": portfolio_manager.current_equity,
            "realized_pnl": portfolio_manager.realized_pnl,
            "peak_equity": portfolio_manager.peak_equity,
            "win_count": portfolio_manager.win_count,
            "loss_count": portfolio_manager.loss_count,
            "closed_trades": [self._serialize_closed_trade(trade) for trade in portfolio_manager.closed_trades],
            "active_position": (
                self._serialize_open_position(portfolio_manager.active_position)
                if portfolio_manager.active_position is not None
                else None
            ),
        }

    def _serialize_closed_trade(self, trade: ClosedTrade) -> dict[str, Any]:
        return {
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
            "notes": list(trade.notes),
            "tags": list(trade.tags),
            "metadata": trade.metadata,
        }

    def _deserialize_closed_trade(self, payload: dict[str, Any]) -> ClosedTrade:
        return ClosedTrade(
            symbol=str(payload["symbol"]),
            timeframe=str(payload["timeframe"]),
            side=Side(str(payload["side"])),
            opened_at=self._parse_timestamp(payload["opened_at"]),
            closed_at=self._parse_timestamp(payload["closed_at"]),
            entry_price=float(payload["entry_price"]),
            exit_price=float(payload["exit_price"]),
            initial_quantity=float(payload["initial_quantity"]),
            realized_pnl=float(payload["realized_pnl"]),
            realized_r=float(payload["realized_r"]),
            reason=str(payload["reason"]),
            notes=tuple(str(item) for item in payload.get("notes", [])),
            tags=tuple(str(item) for item in payload.get("tags", [])),
            metadata=dict(payload.get("metadata", {})),
        )

    def _serialize_open_position(self, position: OpenPosition) -> dict[str, Any]:
        return {
            "symbol": position.symbol,
            "timeframe": position.timeframe,
            "side": position.side.value,
            "opened_at": position.opened_at.isoformat(),
            "entry_price": position.entry_price,
            "stop_price": position.stop_price,
            "initial_stop_price": position.initial_stop_price,
            "initial_quantity": position.initial_quantity,
            "remaining_quantity": position.remaining_quantity,
            "risk_plan": self._serialize_risk_plan(position.risk_plan),
            "source_signal": self._serialize_trade_signal(position.source_signal),
            "realized_pnl": position.realized_pnl,
            "first_partial_taken": position.first_partial_taken,
            "first_partial_fill_price": position.first_partial_fill_price,
            "bars_held": position.bars_held,
            "best_r_multiple": position.best_r_multiple,
            "worst_r_multiple": position.worst_r_multiple,
            "first_target_hit_after_bars": position.first_target_hit_after_bars,
            "follow_through_state": position.follow_through_state,
            "closed_at": position.closed_at.isoformat() if position.closed_at is not None else None,
            "closed_reason": position.closed_reason,
            "broker_metadata": dict(position.broker_metadata),
        }

    def _deserialize_open_position(self, payload: dict[str, Any]) -> OpenPosition:
        closed_at = payload.get("closed_at")
        return OpenPosition(
            symbol=str(payload["symbol"]),
            timeframe=str(payload["timeframe"]),
            side=Side(str(payload["side"])),
            opened_at=self._parse_timestamp(payload["opened_at"]),
            entry_price=float(payload["entry_price"]),
            stop_price=float(payload["stop_price"]),
            initial_stop_price=float(payload["initial_stop_price"]),
            initial_quantity=float(payload["initial_quantity"]),
            remaining_quantity=float(payload["remaining_quantity"]),
            risk_plan=self._deserialize_risk_plan(payload["risk_plan"]),
            source_signal=self._deserialize_trade_signal(payload["source_signal"]),
            realized_pnl=float(payload.get("realized_pnl", 0.0)),
            first_partial_taken=bool(payload.get("first_partial_taken", False)),
            first_partial_fill_price=(
                None
                if payload.get("first_partial_fill_price") is None
                else float(payload["first_partial_fill_price"])
            ),
            bars_held=int(payload.get("bars_held", 0)),
            best_r_multiple=float(payload.get("best_r_multiple", 0.0)),
            worst_r_multiple=float(payload.get("worst_r_multiple", 0.0)),
            first_target_hit_after_bars=(
                None
                if payload.get("first_target_hit_after_bars") is None
                else int(payload["first_target_hit_after_bars"])
            ),
            follow_through_state=str(payload.get("follow_through_state", "developing")),
            closed_at=None if closed_at is None else self._parse_timestamp(closed_at),
            closed_reason=None if payload.get("closed_reason") is None else str(payload["closed_reason"]),
            broker_metadata=dict(payload.get("broker_metadata", {})),
        )

    def _serialize_risk_plan(self, plan: RiskPlan) -> dict[str, Any]:
        return {
            "equity": plan.equity,
            "risk_fraction": plan.risk_fraction,
            "risk_amount": plan.risk_amount,
            "risk_per_unit": plan.risk_per_unit,
            "position_size": plan.position_size,
            "first_partial_at_price": plan.first_partial_at_price,
            "first_partial_fraction": plan.first_partial_fraction,
            "breakeven_after_partial": plan.breakeven_after_partial,
        }

    def _deserialize_risk_plan(self, payload: dict[str, Any]) -> RiskPlan:
        return RiskPlan(
            equity=float(payload["equity"]),
            risk_fraction=float(payload["risk_fraction"]),
            risk_amount=float(payload["risk_amount"]),
            risk_per_unit=float(payload["risk_per_unit"]),
            position_size=float(payload["position_size"]),
            first_partial_at_price=float(payload["first_partial_at_price"]),
            first_partial_fraction=float(payload["first_partial_fraction"]),
            breakeven_after_partial=bool(payload["breakeven_after_partial"]),
        )

    def _serialize_trade_signal(self, signal: TradeSignal) -> dict[str, Any]:
        return {
            "strategy_name": signal.strategy_name,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "side": signal.side.value,
            "generated_at": signal.generated_at.isoformat(),
            "entry_price": signal.entry_price,
            "stop_price": signal.stop_price,
            "first_target_price": signal.first_target_price,
            "confidence": signal.confidence,
            "reasons": list(signal.reasons),
            "metadata": signal.metadata,
        }

    def _deserialize_trade_signal(self, payload: dict[str, Any]) -> TradeSignal:
        return TradeSignal(
            strategy_name=str(payload["strategy_name"]),
            symbol=str(payload["symbol"]),
            timeframe=str(payload["timeframe"]),
            side=Side(str(payload["side"])),
            generated_at=self._parse_timestamp(payload["generated_at"]),
            entry_price=float(payload["entry_price"]),
            stop_price=float(payload["stop_price"]),
            first_target_price=float(payload["first_target_price"]),
            confidence=float(payload["confidence"]),
            reasons=tuple(str(item) for item in payload.get("reasons", [])),
            metadata=dict(payload.get("metadata", {})),
        )

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)
