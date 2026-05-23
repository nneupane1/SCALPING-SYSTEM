"""In-process WebSocket broadcaster placeholder."""

from __future__ import annotations

from collections import deque
from typing import Any, Callable

from .schemas import to_api_payload


class WebSocketBroadcaster:
    """Store and fan out API events.

    This is not a real WebSocket server yet. It gives the backend a stable
    publish interface before the transport layer is wired to FastAPI.
    """

    def __init__(self, buffer_size: int = 1000) -> None:
        self.buffer = deque(maxlen=buffer_size)
        self.subscribers: list[Callable[[dict[str, Any]], None]] = []

    def subscribe(self, handler: Callable[[dict[str, Any]], None]) -> None:
        self.subscribers.append(handler)

    def publish(self, topic: str, payload: Any) -> None:
        message = {"topic": topic, "payload": to_api_payload(payload)}
        self.buffer.append(message)
        for handler in self.subscribers:
            handler(message)
