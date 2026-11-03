"""Retrying publisher for persisted outbox events."""

import logging
from datetime import UTC, datetime, timedelta
from threading import Event

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models import OutboxEvent
from app.services.sender import EventSender, SenderError

logger = logging.getLogger(__name__)
MAX_RETRY_DELAY_SECONDS = 60
PUBLISH_INTERVAL_SECONDS = 1


def publish_pending(
    session_factory: sessionmaker[Session],
    sender: EventSender,
    *,
    now: datetime | None = None,
    batch_size: int = 100,
) -> int:
    """Publish due pending events and persist each success or retry schedule."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    published_count = 0
    with session_factory() as session:
        with session.begin():
            events = session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.status == "pending",
                    OutboxEvent.next_attempt_at <= current_time,
                )
                .order_by(OutboxEvent.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()

            for event in events:
                try:
                    sender.send(event.event_type, event.payload)
                except SenderError:
                    event.attempts += 1
                    retry_seconds = min(
                        2 ** min(event.attempts, 6),
                        MAX_RETRY_DELAY_SECONDS,
                    )
                    event.next_attempt_at = current_time + timedelta(
                        seconds=retry_seconds
                    )
                    logger.exception(
                        "Outbox event %s failed; retrying in %s seconds",
                        event.id,
                        retry_seconds,
                    )
                else:
                    event.status = "sent"
                    event.sent_at = current_time
                    published_count += 1
    return published_count


def run_outbox_publisher(
    session_factory: sessionmaker[Session],
    sender: EventSender,
    stop_event: Event | None = None,
) -> None:
    """Continuously publish pending messages, retrying database failures."""
    stop = Event() if stop_event is None else stop_event
    while not stop.is_set():
        try:
            publish_pending(session_factory, sender)
        except SQLAlchemyError:
            logger.exception("Outbox publisher database operation failed")
        if stop.wait(PUBLISH_INTERVAL_SECONDS):
            return
