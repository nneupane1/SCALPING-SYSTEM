"""Runtime assembly helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.config.models import ConfigBundle
from backend.app.execution.broker_base import Broker, PaperBroker
from backend.app.execution.broker_binance import BinanceBroker
from backend.app.execution.execution_engine import ExecutionEngine
from backend.app.execution.order_manager import OrderManager
from backend.app.portfolio.journal import Journal
from backend.app.portfolio.portfolio_manager import PortfolioManager
from backend.app.risk.risk_manager import RiskManager
from backend.app.risk.trailing_engine import TrailingEngine
from backend.app.scanner.momentum_scanner import MomentumScanner
from backend.app.strategies.pullback_scalp import PullbackScalpStrategy

from .engine import TradingEngine
from .event_bus import EventBus
from .events import Event, EventTopic
from .logger import configure_logging


@dataclass(frozen=True)
class RuntimeContainer:
    """Bundled runtime services."""

    config: ConfigBundle
    event_bus: EventBus
    engine: TradingEngine
    portfolio_manager: PortfolioManager
    journal: Journal
    order_manager: OrderManager
    broker: Broker


def build_runtime(config: ConfigBundle) -> RuntimeContainer:
    """Assemble the first-pass runtime from config."""

    configure_logging(debug=config.system.app.debug)
    active_profile = config.strategy.resolve_profile(config.system.market.execution_timeframe)
    event_bus = EventBus()
    journal = Journal()
    portfolio_manager = PortfolioManager(
        starting_equity=config.system.account.initial_equity,
        journal=journal,
    )
    order_manager = OrderManager(mode=config.system.app.mode)
    broker: Broker
    if config.system.app.mode == "live" and config.risk.execution.allow_live_orders:
        broker = BinanceBroker(
            config=config,
            order_manager=order_manager,
            on_event=lambda event_type, payload: event_bus.publish(
                Event(
                    EventTopic.HEALTH,
                    {"source": "binance_broker", "event_type": event_type, "payload": payload},
                )
            ),
        )
    else:
        broker = PaperBroker(order_manager=order_manager)
    execution_engine = ExecutionEngine(
        order_manager=order_manager,
        broker=broker,
        max_slippage_bps=config.risk.execution.max_slippage_bps,
    )
    risk_manager = RiskManager(risk_config=config.risk)
    trailing_engine = TrailingEngine(risk_config=config.risk)
    scanner = MomentumScanner(
        scanner_config=active_profile.scanner,
        execution_timeframe=active_profile.execution_timeframe,
        profile_name=active_profile.name,
    )
    strategy = PullbackScalpStrategy(
        strategy_config=config.strategy.strategy,
        filter_config=config.strategy.filters,
        trigger_config=active_profile.trigger,
        execution_timeframe=active_profile.execution_timeframe,
        profile=active_profile,
        sessions_config=config.system.sessions,
    )
    engine = TradingEngine(
        execution_timeframe=active_profile.execution_timeframe,
        trigger_timeframe=active_profile.trigger_timeframe,
        clock_timeframe=active_profile.clock_timeframe,
        scanner=scanner,
        strategy=strategy,
        risk_manager=risk_manager,
        execution_engine=execution_engine,
        trailing_engine=trailing_engine,
        portfolio_manager=portfolio_manager,
        event_bus=event_bus,
        session_timezone=config.system.sessions.timezone,
    )
    return RuntimeContainer(
        config=config,
        event_bus=event_bus,
        engine=engine,
        portfolio_manager=portfolio_manager,
        journal=journal,
        order_manager=order_manager,
        broker=broker,
    )
