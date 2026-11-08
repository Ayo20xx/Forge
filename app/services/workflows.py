"""Application workflows for bank-account routes and background workers."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Protocol

from fastapi import Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_bank_account_repository
from app.repository.bank_accounts import BankAccountConflict, BankAccountRepository
from app.repository.ingest import IngestionRepository
from app.repository.outbox import OutboxRepository
from app.repository.polling import PollingRepository
from app.schemas.admin import SyncResponse
from app.schemas.bank_accounts import (
    BankAccountCreate,
    BankAccountData,
    BankAccountResponse,
    ReconciliationResponse,
)
from app.schemas.transactions import BankTransferEvent, TransactionPage, Transfer
from app.services.bank_client import (
    BankError,
    PollingBankClient,
    get_bank_client,
)

logger = logging.getLogger(__name__)
MAX_BACKOFF_SECONDS = 60
MAX_BATCH_SIZE = 100
PUBLISH_INTERVAL_SECONDS = 1


@dataclass(slots=True)
class BankAccountService:
    """Orchestrates bank account operations for HTTP endpoints."""

    repository: BankAccountRepository
    bank_client: PollingBankClient

    def create_bank_account(self, body: BankAccountCreate) -> BankAccountResponse:
        """Create an account at the bank and store its local mapping."""
        try:
            account = BankAccountData.model_validate(
                self.bank_client.create_account(body.customer_reference)
            )
            saved = self.repository.create_bank_account(account)
        except BankError as exc:
            raise HTTPException(
                status_code=502, detail="Bank account creation failed"
            ) from exc
        except BankAccountConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return BankAccountResponse.model_validate(saved)

    def sync_accounts(self) -> SyncResponse:
        """Import existing bank accounts without interpreting their core references."""
        try:
            accounts = [
                BankAccountData.model_validate(account)
                for account in self.bank_client.list_accounts()
            ]
            imported = self.repository.sync_bank_accounts(accounts)
        except BankError as exc:
            raise HTTPException(status_code=502, detail="Bank account sync failed") from exc
        except BankAccountConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return SyncResponse(
            imported_count=len(imported),
            accounts=[BankAccountResponse.model_validate(account) for account in imported],
        )

    def reconcile_bank_account(self, account_id: str) -> ReconciliationResponse:
        """Compare stored transaction total with the bank's current booked balance."""
        bank_accounts = self.repository.find_bank_accounts(account_id)
        if not bank_accounts:
            raise HTTPException(status_code=404, detail="Bank account not found")
        if len(bank_accounts) > 1:
            raise HTTPException(
                status_code=409,
                detail="Account ID is ambiguous across banks",
            )
        bank_account = bank_accounts[0]

        try:
            bank_snapshot = BankAccountData.model_validate(
                self.bank_client.get_balance(bank_account.account_id)
            )
        except BankError as exc:
            raise HTTPException(
                status_code=502, detail="Bank balance request failed"
            ) from exc

        if (
            bank_snapshot.bank_id != bank_account.bank_id
            or bank_snapshot.account_id != bank_account.account_id
            or bank_snapshot.customer_reference != bank_account.customer_reference
        ):
            raise HTTPException(status_code=502, detail="Bank returned a mismatched account")

        # booked_balance_minor is only a comparison snapshot, never a ledger credit.
        stored_total = self.repository.stored_transaction_total(bank_account.id)
        bank_total = bank_snapshot.booked_balance_minor
        return ReconciliationResponse(
            account_id=bank_account.account_id,
            stored_total_minor=stored_total,
            bank_balance_minor=bank_total,
            difference_minor=bank_total - stored_total,
            matches=stored_total == bank_total,
        )


def get_bank_account_service(
    repository: BankAccountRepository = Depends(get_bank_account_repository),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> BankAccountService:
    """Build the service from request-scoped FastAPI dependencies."""
    return BankAccountService(repository=repository, bank_client=bank_client)


def ingest_batch(
    repository: IngestionRepository,
    events: Sequence[BankTransferEvent | Transfer | Mapping[str, object]],
    next_cursor: int,
    bank_id: str | None = None,
) -> None:
    """Normalize one bank page and persist it through the repository."""
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


def publish_pending(
    repository: OutboxRepository,
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
    repository: OutboxRepository,
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


class TransactionSource(Protocol):
    def get_transactions(self, *, after: int) -> TransactionPage: ...


class StopSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


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
    polling_repository: PollingRepository,
    ingestion_repository: IngestionRepository,
    interval_seconds: int = 30,
    stop_event: StopSignal | None = None,
) -> None:
    """Poll every interval, draining pages and backing off after recoverable errors."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    stop = Event() if stop_event is None else stop_event
    backoff_seconds = 1

    while not stop.is_set():
        try:
            expected_bank_id, cursor = polling_repository.latest_cursor()
            while not stop.is_set():
                page = bank_client.get_transactions(after=cursor)
                _validate_page(page, cursor, expected_bank_id)
                ingest_batch(
                    ingestion_repository,
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
