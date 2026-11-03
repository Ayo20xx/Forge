"""Resumable Polling Bank transaction ingestion loop."""

import logging
from collections.abc import Sequence
from threading import Event

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models import PollCursor
from app.services.bank_client import (
    BankError,
    BankTransfer,
    PollingBankClient,
    TransactionPage,
)
from app.services.ingest import ingest_batch

logger = logging.getLogger(__name__)
MAX_BACKOFF_SECONDS = 60


def _stored_cursor(session_factory: sessionmaker[Session]) -> tuple[str | None, int]:
    with session_factory() as session:
        cursor = session.execute(
            select(PollCursor.bank_id, PollCursor.cursor)
            .order_by(PollCursor.updated_at.desc())
            .limit(1)
        ).one_or_none()
    return (None, 0) if cursor is None else (cursor.bank_id, cursor.cursor)


def _validate_page(
    page: TransactionPage, after: int, expected_bank_id: str | None
) -> tuple[str, Sequence[BankTransfer], int, bool]:
    if not isinstance(page, dict):
        raise ValueError("Polling Bank returned an invalid transaction page")

    bank_id = page.get("bank_id")
    events = page.get("data")
    next_cursor = page.get("next_cursor")
    has_more = page.get("has_more")
    if not isinstance(bank_id, str) or not bank_id:
        raise ValueError("Polling Bank transaction page has an invalid bank_id")
    if expected_bank_id is not None and bank_id != expected_bank_id:
        raise ValueError("Polling Bank transaction page changed bank identity")
    if not isinstance(events, list):
        raise ValueError("Polling Bank transaction page has invalid data")
    if (
        not isinstance(next_cursor, int)
        or isinstance(next_cursor, bool)
        or next_cursor < after
    ):
        raise ValueError("Polling Bank transaction page has an invalid next_cursor")
    if not isinstance(has_more, bool):
        raise ValueError("Polling Bank transaction page has invalid has_more")
    if has_more and next_cursor == after:
        raise ValueError("Polling Bank transaction page did not advance its cursor")
    return bank_id, events, next_cursor, has_more


def run_poller(
    bank_client: PollingBankClient,
    session_factory: sessionmaker[Session],
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
            expected_bank_id, cursor = _stored_cursor(session_factory)
            while not stop.is_set():
                page = bank_client.get_transactions(after=cursor)
                bank_id, events, next_cursor, has_more = _validate_page(
                    page, cursor, expected_bank_id
                )
                with session_factory() as session:
                    ingest_batch(session, events, next_cursor, bank_id=bank_id)
                expected_bank_id = bank_id
                cursor = next_cursor
                if not has_more:
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
