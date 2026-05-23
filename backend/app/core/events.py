"""Internal event primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventTopic(str, Enum):
    """Named event channels used inside the runtime."""

    MARKET_TICK = "market.tick"
    CANDLE_CLOSED = "market.candle_closed"
    SNAPSHOT_READY = "market.snapshot_ready"
    SCANNER_UPDATED = "scanner.updated"
    SIGNAL_EMITTED = "strategy.signal_emitted"
    ORDER_SUBMITTED = "execution.order_submitted"
    POSITION_UPDATED = "execution.position_updated"
    PORTFOLIO_UPDATED = "portfolio.updated"
    HEALTH = "system.health"


@dataclass(frozen=True)
class Event:
    """A timestamped event sent over the in-process event bus."""

    topic: EventTopic
    payload: Any
    emitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

