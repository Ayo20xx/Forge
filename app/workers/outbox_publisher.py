"""Background loop for publishing pending outbox events."""

import logging
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from app.services.outbox_publisher import OutboxPublisher
from app.workers.common import StopSignal

logger = logging.getLogger(__name__)
PUBLISH_INTERVAL_SECONDS = 1





def run_outbox_publisher(
    publisher: OutboxPublisher,
    stop_event: StopSignal | None = None,
) -> None:
    """Publish continuously, retrying database failures on the next interval."""
    stop = Event() if stop_event is None else stop_event
    while not stop.is_set():
        try:
            publisher.publish_pending()
        except SQLAlchemyError:
            logger.exception("Outbox publisher database operation failed")
        if stop.wait(PUBLISH_INTERVAL_SECONDS):
            return
