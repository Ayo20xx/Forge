"""Background loop for polling and ingesting bank transactions."""

import logging
from threading import Event
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.services.bank_client import BankError
from app.services.transaction_ingestion import TransactionSource

logger = logging.getLogger(__name__)
MAX_BACKOFF_SECONDS = 60


class StopSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class PollingService(Protocol):
    def poll_once(self, bank_client: TransactionSource) -> None: ...


def run_poller(
    ingestion_service: PollingService,
    bank_client: TransactionSource,
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
            ingestion_service.poll_once(bank_client)
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
