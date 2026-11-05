"""Database operations for publishing and retrying outbox events."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import OutboxEvent

logger = logging.getLogger(__name__)


class OutboxRepository:
    """Claims pending events and persists their delivery state."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def publish_pending(
        self,
        send_event: Callable[[str, dict[str, object]], None],
        retry_error: type[Exception],
        now: datetime,
        batch_size: int,
    ) -> int:
        published_count = 0
        with self._session_factory.begin() as session:
            events = session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.status == "pending",
                    OutboxEvent.next_attempt_at <= now,
                )
                .order_by(OutboxEvent.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()
            for event in events:
                try:
                    send_event(event.event_type, event.payload)
                except retry_error:
                    event.attempts += 1
                    retry_seconds = min(2 ** min(event.attempts, 6), 60)
                    event.next_attempt_at = now + timedelta(seconds=retry_seconds)
                    logger.exception(
                        "Outbox event %s failed; retrying in %s seconds",
                        event.id,
                        retry_seconds,
                    )
                else:
                    event.status = "sent"
                    event.sent_at = now
                    published_count += 1
        return published_count
