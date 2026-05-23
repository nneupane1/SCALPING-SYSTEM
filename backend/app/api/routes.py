"""Route registry placeholder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RouteDefinition:
    """A route contract that can later be mounted on FastAPI."""

    path: str
    method: str
    handler_name: str


def default_routes() -> tuple[RouteDefinition, ...]:
    return (
        RouteDefinition(path="/health", method="GET", handler_name="health"),
        RouteDefinition(path="/portfolio", method="GET", handler_name="portfolio_snapshot"),
        RouteDefinition(path="/journal", method="GET", handler_name="journal_entries"),
    )

