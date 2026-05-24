"""Main orchestration for one closed-candle evaluation cycle."""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.app.portfolio.portfolio_manager import PortfolioManager

from .events import Event, EventTopic
from .models import (
    ManagementDecision,
    MarketSnapshot,
    PortfolioSnapshot,
    RiskPlan,
    ScannerDecision,
    TradeSignal,
)


@dataclass(frozen=True)
class EngineCycleResult:
    """A structured description of one engine pass."""

    snapshot: MarketSnapshot
    scanner_decision: ScannerDecision | None
    signal: TradeSignal | None
    risk_plan: RiskPlan | None
    management_decisions: tuple[ManagementDecision, ...]
    portfolio: PortfolioSnapshot


class TradingEngine:
    """Thin orchestrator that delegates decisions to specialized modules."""

    def __init__(
        self,
        execution_timeframe: str,
        scanner,
        strategy,
        risk_manager,
        execution_engine,
        trailing_engine,
        portfolio_manager: PortfolioManager,
        event_bus,
        session_timezone: str,
    ) -> None:
        self.execution_timeframe = execution_timeframe
        self.scanner = scanner
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.execution_engine = execution_engine
        self.trailing_engine = trailing_engine
        self.portfolio_manager = portfolio_manager
        self.event_bus = event_bus
        self.session_timezone = session_timezone

    def process_snapshot(self, snapshot: MarketSnapshot) -> EngineCycleResult:
        """Run one full market-state evaluation pass."""

        self.event_bus.publish(Event(EventTopic.SNAPSHOT_READY, snapshot))
        signal: TradeSignal | None = None
        risk_plan: RiskPlan | None = None
        scanner_decision: ScannerDecision | None = None
        management_decisions: tuple[ManagementDecision, ...] = ()

        active_position = self.portfolio_manager.active_position
        latest_candle = snapshot.latest(self.execution_timeframe)

        if active_position is not None and latest_candle is not None:
            management_decisions = self.trailing_engine.evaluate(
                position=active_position,
                candles=snapshot.series(self.execution_timeframe),
            )
            for decision in management_decisions:
                closed_trade = self.execution_engine.apply_management(
                    position=active_position,
                    decision=decision,
                    occurred_at=latest_candle.close_time,
                )
                if closed_trade is not None:
                    self.portfolio_manager.close_position(closed_trade)
            self.portfolio_manager.sync_active_position(active_position)
        elif latest_candle is not None:
            scanner_decision = self.scanner.scan(snapshot)
            self.event_bus.publish(Event(EventTopic.SCANNER_UPDATED, scanner_decision))
            if scanner_decision.is_tradeable:
                signal = self.strategy.evaluate(snapshot, scanner_decision)
                if signal is not None:
                    signal = self._apply_day_feedback(signal=signal, occurred_at=latest_candle.close_time)
                if signal is not None:
                    self.event_bus.publish(Event(EventTopic.SIGNAL_EMITTED, signal))
                    try:
                        risk_plan = self.risk_manager.build_plan(
                            signal=signal,
                            equity=self.portfolio_manager.current_equity,
                        )
                        position = self.execution_engine.execute_signal(signal, risk_plan)
                    except ValueError as exc:
                        self.event_bus.publish(
                            Event(
                                EventTopic.HEALTH,
                                {
                                    "stage": "entry_validation",
                                    "message": str(exc),
                                },
                            )
                        )
                    else:
                        self.portfolio_manager.open_position(position)
                        self.event_bus.publish(Event(EventTopic.ORDER_SUBMITTED, position))

        portfolio = self.portfolio_manager.snapshot()
        self.event_bus.publish(Event(EventTopic.PORTFOLIO_UPDATED, portfolio))
        return EngineCycleResult(
            snapshot=snapshot,
            scanner_decision=scanner_decision,
            signal=signal,
            risk_plan=risk_plan,
            management_decisions=management_decisions,
            portfolio=portfolio,
        )

    def _apply_day_feedback(self, *, signal: TradeSignal, occurred_at) -> TradeSignal | None:
        summary = self.portfolio_manager.build_day_summary(occurred_at, self.session_timezone)
        limits = self.risk_manager.risk_config.risk
        if summary.trade_count >= limits.max_trades_per_day:
            self.event_bus.publish(
                Event(
                    EventTopic.HEALTH,
                    {
                        "stage": "daily_guard",
                        "message": f"max trades per day reached ({summary.trade_count}/{limits.max_trades_per_day})",
                    },
                )
            )
            return None
        if summary.realized_r <= -limits.max_daily_loss_r:
            self.event_bus.publish(
                Event(
                    EventTopic.HEALTH,
                    {
                        "stage": "daily_guard",
                        "message": f"max daily loss reached ({summary.realized_r:.2f}R)",
                    },
                )
            )
            return None
        if summary.consecutive_losses >= limits.max_consecutive_losses:
            self.event_bus.publish(
                Event(
                    EventTopic.HEALTH,
                    {
                        "stage": "daily_guard",
                        "message": f"consecutive loss guard active ({summary.consecutive_losses})",
                    },
                )
            )
            return None

        feedback_multiplier = 1.0
        feedback_reason = "neutral"
        if summary.trade_count >= limits.minimum_closed_trades_for_day_scaling:
            if summary.realized_r >= limits.good_day_threshold_r and summary.win_count >= summary.loss_count:
                feedback_multiplier = limits.good_day_risk_multiplier
                feedback_reason = "good_day"
            elif summary.realized_r <= limits.bad_day_threshold_r or summary.loss_count > summary.win_count:
                feedback_multiplier = limits.bad_day_risk_multiplier
                feedback_reason = "bad_day"

        metadata = dict(signal.metadata)
        metadata["day_trade_count"] = summary.trade_count
        metadata["day_realized_r"] = summary.realized_r
        metadata["day_feedback_multiplier"] = feedback_multiplier
        metadata["day_feedback_reason"] = feedback_reason
        metadata["risk_fraction_multiplier"] = float(metadata.get("risk_fraction_multiplier", 1.0)) * feedback_multiplier
        reasons = signal.reasons
        if feedback_reason == "good_day":
            reasons = reasons + ("session is behaving cleanly; risk scaled modestly upward",)
        elif feedback_reason == "bad_day":
            reasons = reasons + ("session is behaving poorly; risk scaled down",)
        return replace(signal, metadata=metadata, reasons=reasons)
