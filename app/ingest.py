# Defines the ingestion function contract for safely applying bank event pages.

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.bank_client import BankTransfer


def ingest_batch(
    session: Session,
    events: Sequence[BankTransfer],
    next_cursor: int,
) -> None:
    """TODO: atomically persist one bank page and its next poll cursor.

    Deduplicate deposits on (bank_id, transaction_id). Credit amount_minor only,
    never booked_balance_minor or available_balance_minor. Park unknown or
    conflicting account mappings in unmapped_transactions, never guess a user.
    Ledger rows are append-only and all money is integer cents. Save rows and
    cursor in this same transaction; an error must leave the cursor unchanged.
    """
    raise NotImplementedError
