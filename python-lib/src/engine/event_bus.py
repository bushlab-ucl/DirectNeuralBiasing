"""Lightweight publish/subscribe event bus.

Modules and the pipeline use this to decouple event producers from
event consumers. An EventDetector publishes events; trigger handlers,
loggers, or other modules subscribe to specific event types.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from dnb.core.types import Event, EventType

logger = logging.getLogger(__name__)

EventCallback = Callable[[Event], None]


class EventBus:
    """Thread-safe pub/sub bus for neural events.

    Subscribe to specific event types or to all events. Callbacks are
    invoked synchronously on the processing thread — keep them fast.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType | None, list[EventCallback]] = defaultdict(list)

    def subscribe(
        self,
        callback: EventCallback,
        event_type: EventType | None = None,
    ) -> None:
        """Register a callback for events.

        Args:
            callback: Function to call when a matching event is published.
            event_type: Specific type to listen for, or None for all events.
        """
        self._subscribers[event_type].append(callback)

    def publish(self, event: Event) -> None:
        """Dispatch an event to all matching subscribers.

        Calls type-specific subscribers first, then wildcard subscribers.
        """
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
        """Remove all subscribers."""
        self._subscribers.clear()