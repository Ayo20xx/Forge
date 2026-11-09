"""Ingest bank transaction pages and run the polling loop."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Event
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.repository.ingest import IngestionRepository
from app.repository.polling import PollingRepository
from app.schemas.transactions import BankTransferEvent, TransactionPage, Transfer
from app.services.bank_client import BankError

logger = logging.getLogger(__name__)
MAX_BACKOFF_SECONDS = 60


class TransactionSource(Protocol):
    def get_transactions(self, *, after: int) -> TransactionPage: ...


class StopSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


def _ingest_batch(
    repository: IngestionRepository,
    events: Sequence[BankTransferEvent | Transfer | Mapping[str, object]],
    next_cursor: int,
    bank_id: str | None,
) -> None:
    if next_cursor < 0:
        raise ValueError("next_cursor must be non-negative")

    transfers = [
        event
        if isinstance(event, Transfer)
        else Transfer.from_bank_event(
            event
            if isinstance(event, BankTransferEvent)
            else BankTransferEvent.model_validate(event)
        )
        for event in events
    ]
    if bank_id is None:
        if not transfers:
            raise ValueError("bank_id is required when ingesting an empty page")
        bank_id = transfers[0].bank_id
    if not bank_id:
        raise ValueError("bank_id must be a non-empty string")
    if any(transfer.bank_id != bank_id for transfer in transfers):
        raise ValueError("all events must belong to the cursor bank")

    repository.ingest_batch(transfers, next_cursor, bank_id)


@dataclass(slots=True)
class TransactionIngestionService:
    """Imports transaction pages and manages the bank cursor polling loop."""

    ingestion_repository: IngestionRepository
    polling_repository: PollingRepository

    def ingest_batch(
        self,
        events: Sequence[BankTransferEvent | Transfer | Mapping[str, object]],
        next_cursor: int,
        bank_id: str | None = None,
    ) -> None:
        """Normalize one bank page and persist it through the repository."""
        _ingest_batch(self.ingestion_repository, events, next_cursor, bank_id)

    @staticmethod
    def _validate_page(
        page: TransactionPage, after: int, expected_bank_id: str | None
    ) -> None:
        if expected_bank_id is not None and page.bank_id != expected_bank_id:
            raise ValueError("Polling Bank transaction page changed bank identity")
        if page.next_cursor < after:
            raise ValueError("Polling Bank transaction page has an invalid next_cursor")
        if page.has_more and page.next_cursor == after:
            raise ValueError("Polling Bank transaction page did not advance its cursor")

    def run(
        self,
        bank_client: TransactionSource,
        interval_seconds: int = 30,
        stop_event: StopSignal | None = None,
    ) -> None:
        """Poll at intervals, draining pages and backing off after recoverable errors."""
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        stop = Event() if stop_event is None else stop_event
        backoff_seconds = 1

        while not stop.is_set():
            try:
                expected_bank_id, cursor = self.polling_repository.latest_cursor()
                while not stop.is_set():
                    page = bank_client.get_transactions(after=cursor)
                    self._validate_page(page, cursor, expected_bank_id)
                    self.ingest_batch(
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


def ingest_batch(
    repository: IngestionRepository,
    events: Sequence[BankTransferEvent | Transfer | Mapping[str, object]],
    next_cursor: int,
    bank_id: str | None = None,
) -> None:
    """Normalize and persist a bank transaction page."""
    _ingest_batch(repository, events, next_cursor, bank_id)


def run_poller(
    bank_client: TransactionSource,
    polling_repository: PollingRepository,
    ingestion_repository: IngestionRepository,
    interval_seconds: int = 30,
    stop_event: StopSignal | None = None,
) -> None:
    """Run the transaction polling loop."""
    TransactionIngestionService(
        ingestion_repository=ingestion_repository,
        polling_repository=polling_repository,
    ).run(bank_client, interval_seconds, stop_event)
