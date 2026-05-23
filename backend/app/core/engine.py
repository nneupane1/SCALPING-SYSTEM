"""Main orchestration for one closed-candle evaluation cycle."""

from __future__ import annotations

from dataclasses import dataclass

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
    ) -> None:
        self.execution_timeframe = execution_timeframe
        self.scanner = scanner
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.execution_engine = execution_engine
        self.trailing_engine = trailing_engine
        self.portfolio_manager = portfolio_manager
        self.event_bus = event_bus

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
