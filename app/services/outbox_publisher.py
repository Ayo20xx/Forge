"""Publish pending transaction outbox events."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.repository.outbox import OutboxRepository

MAX_BATCH_SIZE = 100


class EventSender(Protocol):
    def send(self, event_type: str, payload: dict[str, object]) -> None: ...


class LoggingSender:
    """Development sender that records published events in the application log."""

    def send(self, event_type: str, payload: dict[str, object]) -> None:
        logging.getLogger(__name__).info(
            "Published outbox event %s: %s",
            event_type,
            payload,
        )


class SenderError(Exception):
    """Raised when an outgoing event cannot be delivered."""


@dataclass(slots=True)
class OutboxPublisher:
    """Publishes due events and runs the continuous publisher loop."""

    repository: OutboxRepository
    sender: EventSender

    def publish_pending(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = MAX_BATCH_SIZE,
    ) -> int:
        """Publish due pending events and persist their success or retry schedule."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        current_time = now or datetime.now(UTC)
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return self.repository.publish_pending(
            self.sender.send, SenderError, current_time, batch_size
        )
