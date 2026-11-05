"""Resumable Polling Bank transaction ingestion loop."""

import logging
from threading import Event
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.repository import Repository
from app.schemas import TransactionPage
from app.services.bank_client import BankError
from app.services.ingest import ingest_batch

logger = logging.getLogger(__name__)
MAX_BACKOFF_SECONDS = 60


class TransactionSource(Protocol):
    def get_transactions(self, *, after: int) -> TransactionPage: ...


def _validate_page(
    page: TransactionPage, after: int, expected_bank_id: str | None
) -> None:
    if expected_bank_id is not None and page.bank_id != expected_bank_id:
        raise ValueError("Polling Bank transaction page changed bank identity")
    if page.next_cursor < after:
        raise ValueError("Polling Bank transaction page has an invalid next_cursor")
    if page.has_more and page.next_cursor == after:
        raise ValueError("Polling Bank transaction page did not advance its cursor")


def run_poller(
    bank_client: TransactionSource,
    repository: Repository,
    interval_seconds: int = 30,
    stop_event: Event | None = None,
) -> None:
    """Poll every interval, draining pages and backing off after recoverable errors."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    stop = Event() if stop_event is None else stop_event
    backoff_seconds = 1

    while not stop.is_set():
        try:
            expected_bank_id, cursor = repository.latest_cursor()
            while not stop.is_set():
                page = bank_client.get_transactions(after=cursor)
                _validate_page(page, cursor, expected_bank_id)
                ingest_batch(
                    repository,
                    page.data,
                    page.next_cursor,
                    bank_id=page.bank_id,
                )
                expected_bank_id = page.bank_id
                cursor = page.next_cursor
                if not page.has_more:
                    break
            backoff_seconds = 1
            if stop.wait(interval_seconds):
                return
        except (BankError, SQLAlchemyError, ValueError):
            logger.exception(
                "Polling Bank ingestion failed; retrying in %s seconds",
                backoff_seconds,
            )
            if stop.wait(backoff_seconds):
                return
            backoff_seconds = min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)
