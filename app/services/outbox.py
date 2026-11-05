"""Retrying publisher for persisted outbox events."""

import logging
from datetime import UTC, datetime
from threading import Event
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.repository import Repository

logger = logging.getLogger(__name__)
MAX_BATCH_SIZE = 100
PUBLISH_INTERVAL_SECONDS = 1


class SenderError(Exception):
    """Raised when an outgoing event cannot be delivered."""


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


def publish_pending(
    repository: Repository,
    sender: EventSender,
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
    return repository.publish_pending(
        sender.send, SenderError, current_time, batch_size
    )


def run_outbox_publisher(
    repository: Repository,
    sender: EventSender,
    stop_event: Event | None = None,
) -> None:
    """Continuously publish pending messages, retrying database failures."""
    stop = Event() if stop_event is None else stop_event
    while not stop.is_set():
        try:
            publish_pending(repository, sender)
        except SQLAlchemyError:
            logger.exception("Outbox publisher database operation failed")
        if stop.wait(PUBLISH_INTERVAL_SECONDS):
            return
