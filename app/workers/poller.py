"""Background loop for polling and ingesting bank transactions."""

import logging
from threading import Event
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.services.bank_client import BankError
from app.workers.common import StopSignal

logger = logging.getLogger(__name__)
MAX_BACKOFF_SECONDS = 60



class PollingService(Protocol):
    def poll_once(self) -> bool: ...


def run_poller(
    ingestion_service: PollingService,
    interval_seconds: int = 30,
    stop_event: StopSignal | None = None,
) -> None:
    """Run polling rounds, waiting between successes and backing off on errors."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    stop = Event() if stop_event is None else stop_event
    backoff_seconds = 1

    while not stop.is_set():
        try:
            has_more = ingestion_service.poll_once()
            while has_more and not stop.is_set():
                has_more = ingestion_service.poll_once()
        except (BankError, SQLAlchemyError, ValueError):
            logger.exception(
                "Polling Bank ingestion failed; retrying in %s seconds",
                backoff_seconds,
            )
            if stop.wait(backoff_seconds):
                return
            backoff_seconds = min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)
        else:
            backoff_seconds = 1
            if stop.wait(interval_seconds):
                return
