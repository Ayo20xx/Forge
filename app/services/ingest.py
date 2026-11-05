"""Normalize validated bank events and delegate atomic persistence."""

from collections.abc import Mapping, Sequence

from app.repository import Repository
from app.schemas import BankTransferEvent, Transfer


def ingest_batch(
    repository: Repository,
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
