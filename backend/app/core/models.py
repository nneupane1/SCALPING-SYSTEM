"""Shared domain models used across the trading runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.data.models import Candle


class RuntimeMode(str, Enum):
    """System execution modes."""

    REPLAY = "replay"
    PAPER = "paper"
    LIVE = "live"


class Side(str, Enum):
    """Trade direction."""

    LONG = "long"
    SHORT = "short"

    @property
    def multiplier(self) -> int:
        return 1 if self is Side.LONG else -1


class ScannerState(str, Enum):
    """Scanner state progression."""

    INACTIVE = "inactive"
    IMPULSE_FOUND = "impulse_found"
    PULLBACK_VALID = "pullback_valid"
    READY = "ready"


class ManagementAction(str, Enum):
    """Position-management actions."""

    HOLD = "hold"
    TAKE_PARTIAL = "take_partial"
    MOVE_STOP = "move_stop"
    EXIT = "exit"


@dataclass(frozen=True)
class MarketSnapshot:
    """The closed-candle market state visible to the trading engine."""

    symbol: str
    generated_at: datetime
    candles: dict[str, tuple["Candle", ...]]

    def series(self, timeframe: str) -> tuple["Candle", ...]:
        return self.candles.get(timeframe, ())

    def latest(self, timeframe: str) -> "Candle | None":
        series = self.series(timeframe)
        return series[-1] if series else None


@dataclass(frozen=True)
class ScannerDecision:
    """Scanner output describing whether the market state is tradable."""

    state: ScannerState
    side: Side | None
    impulse_candle: "Candle | None"
    pullback_candles: tuple["Candle", ...]
    trigger_level: float | None
    invalidation_level: float | None
    momentum_score: float
    pullback_score: float
    reasons: tuple[str, ...]
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def is_tradeable(self) -> bool:
        return self.state is ScannerState.READY and self.side is not None


@dataclass(frozen=True)
class TradeSignal:
    """A rule-based trade idea emitted by the strategy layer."""

    strategy_name: str
    symbol: str
    timeframe: str
    side: Side
    generated_at: datetime
    entry_price: float
    stop_price: float
    first_target_price: float
    confidence: float
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.stop_price)


@dataclass(frozen=True)
class RiskPlan:
    """Position-sizing result built from a signal and account state."""

    equity: float
    risk_fraction: float
    risk_amount: float
    risk_per_unit: float
    position_size: float
    first_partial_at_price: float
    first_partial_fraction: float
    breakeven_after_partial: bool


@dataclass
class OpenPosition:
    """Mutable state for an open trade."""

    symbol: str
    timeframe: str
    side: Side
    opened_at: datetime
    entry_price: float
    stop_price: float
    initial_stop_price: float
    initial_quantity: float
    remaining_quantity: float
    risk_plan: RiskPlan
    source_signal: TradeSignal
    realized_pnl: float = 0.0
    first_partial_taken: bool = False
    first_partial_fill_price: float | None = None
    bars_held: int = 0
    best_r_multiple: float = 0.0
    worst_r_multiple: float = 0.0
    first_target_hit_after_bars: int | None = None
    follow_through_state: str = "developing"
    closed_at: datetime | None = None
    closed_reason: str | None = None
    broker_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def initial_risk_amount(self) -> float:
        return self.risk_plan.risk_amount

    @property
    def direction_multiplier(self) -> int:
        return self.side.multiplier

    def current_r_multiple(self, last_price: float) -> float:
        delta = (last_price - self.entry_price) * self.direction_multiplier
        return delta / self.risk_plan.risk_per_unit if self.risk_plan.risk_per_unit else 0.0

    def unrealized_pnl(self, last_price: float) -> float:
        return (last_price - self.entry_price) * self.direction_multiplier * self.remaining_quantity


@dataclass(frozen=True)
class ManagementDecision:
    """A single management action to be applied to an open position."""

    action: ManagementAction
    reason: str
    price: float | None = None
    quantity: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClosedTrade:
    """A realized trade outcome."""

    symbol: str
    timeframe: str
    side: Side
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    exit_price: float
    initial_quantity: float
    realized_pnl: float
    realized_r: float
    reason: str
    notes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JournalEntry:
    """Human-readable event in the system journal."""

    timestamp: datetime
    stage: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Portfolio state exposed to the UI and API layers."""

    starting_equity: float
    current_equity: float
    realized_pnl: float
    closed_trade_count: int
    win_count: int
    loss_count: int
    peak_equity: float
    drawdown: float
    active_position: OpenPosition | None

    @property
    def win_rate(self) -> float:
        if self.closed_trade_count == 0:
            return 0.0
        return self.win_count / self.closed_trade_count
