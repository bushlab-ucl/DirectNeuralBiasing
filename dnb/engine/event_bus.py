from __future__ import annotations
import logging
from collections import defaultdict
from typing import Callable
from dnb.core.types import Event, EventType
logger = logging.getLogger(__name__)
EventCallback = Callable[[Event], None]

class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[EventType | None, list[EventCallback]] = defaultdict(list)

    def subscribe(self, callback: EventCallback, event_type: EventType | None = None) -> None:
        self._subscribers[event_type].append(callback)

    def publish(self, event: Event) -> None:
        for cb in self._subscribers.get(event.event_type, []):
            try:
                cb(event)
            except Exception:
                logger.exception("Error in event callback for %s", event.event_type)
        for cb in self._subscribers.get(None, []):
            try:
                cb(event)
            except Exception:
                logger.exception("Error in wildcard event callback")

    def clear(self) -> None:
        self._subscribers.clear()