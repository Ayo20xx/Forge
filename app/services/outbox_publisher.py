"""Publish pending transaction outbox events."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.repository.outbox import OutboxRepository

logger = logging.getLogger(__name__)
MAX_BATCH_SIZE = 100
PUBLISH_INTERVAL_SECONDS = 1


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

    def run(self, stop_event: Event | None = None) -> None:
        """Continuously publish pending messages, retrying database failures."""
        stop = Event() if stop_event is None else stop_event
        while not stop.is_set():
            try:
                self.publish_pending()
            except SQLAlchemyError:
                logger.exception("Outbox publisher database operation failed")
            if stop.wait(PUBLISH_INTERVAL_SECONDS):
                return


def publish_pending(
    repository: OutboxRepository,
    sender: EventSender,
    *,
    now: datetime | None = None,
    batch_size: int = MAX_BATCH_SIZE,
) -> int:
    """Publish due pending events through the configured sender."""
    return OutboxPublisher(repository, sender).publish_pending(
        now=now, batch_size=batch_size
    )


def run_outbox_publisher(
    repository: OutboxRepository,
    sender: EventSender,
    stop_event: Event | None = None,
) -> None:
    """Run the continuous outbox publisher loop."""
    OutboxPublisher(repository, sender).run(stop_event)
