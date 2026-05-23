"""A minimal synchronous in-process event bus."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, DefaultDict

from .events import Event, EventTopic

EventHandler = Callable[[Event], None]


class EventBus:
    """Publish-subscribe helper used to keep module coupling explicit."""

    def __init__(self) -> None:
        self._subscriptions: DefaultDict[EventTopic, list[EventHandler]] = defaultdict(list)

    def subscribe(self, topic: EventTopic, handler: EventHandler) -> None:
        self._subscriptions[topic].append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._subscriptions.get(event.topic, []):
            handler(event)

