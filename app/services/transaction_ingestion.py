"""Ingest bank transaction pages into the database.."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.repository.ingest import IngestionRepository
from app.repository.polling import PollingRepository
from app.schemas.transactions import BankTransferEvent, TransactionPage, Transfer


class TransactionSource(Protocol):
    def get_transactions(self, *, after: int) -> TransactionPage: ...


@dataclass(slots=True)
class TransactionIngestionService:
    """Imports bank transaction pages and advances the bank cursor."""

    ingestion_repository: IngestionRepository
    polling_repository: PollingRepository
    bank_client: TransactionSource

    def ingest_batch(
        self,
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

        self.ingestion_repository.ingest_batch(transfers, next_cursor, bank_id)

    def poll_once(self) -> bool:
        """Fetch and ingest one page, returning whether another page is available."""
        expected_bank_id, cursor = self.polling_repository.latest_cursor()
        page = self.bank_client.get_transactions(after=cursor)
        self._validate_page(page, cursor, expected_bank_id)
        self.ingest_batch(
            page.data,
            page.next_cursor,
            bank_id=page.bank_id,
        )
        return page.has_more

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
