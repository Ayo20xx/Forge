"""Atomically persist normalized Polling Bank transaction pages."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import (
    BankAccount,
    BankTransaction,
    OutboxEvent,
    PollCursor,
    UnmappedTransaction,
)
from app.services.adapter import PollingAdapter, Transfer
from app.services.bank_client import BankTransfer


def _insert_do_nothing(
    session: Session, model: type[Any], values: dict[str, object]
) -> Any:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(model).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(model).values(**values)
    else:
        raise RuntimeError(f"Unsupported database dialect for ingestion: {dialect}")
    return statement


def _park_event(session: Session, event: Transfer, reason: str) -> None:
    statement = _insert_do_nothing(
        session,
        UnmappedTransaction,
        {
            "bank_id": event.bank_id,
            "account_id": event.account_id,
            "transaction_id": event.transaction_id,
            "raw_payload": event.raw_payload,
            "reason": reason,
        },
    )
    session.execute(statement.on_conflict_do_nothing())


def ingest_batch(
    session: Session,
    events: Sequence[BankTransfer | Transfer],
    next_cursor: int,
    bank_id: str | None = None,
) -> None:
    """Persist transactions, outbox records, unmapped events, and cursor atomically."""
    if next_cursor < 0:
        raise ValueError("next_cursor must be non-negative")

    adapter = PollingAdapter()
    transfers = [
        event if isinstance(event, Transfer) else adapter.adapt(event)
        for event in events
    ]
    if bank_id is None:
        if not transfers:
            raise ValueError("bank_id is required when ingesting an empty page")
        bank_id = transfers[0].bank_id
    if not bank_id:
        raise ValueError("bank_id must be a non-empty string")
    if any(event.bank_id != bank_id for event in transfers):
        raise ValueError("all events must belong to the cursor bank")

    with session.begin():
        for event in transfers:
            duplicate = session.scalar(
                select(BankTransaction.id).where(
                    BankTransaction.bank_id == event.bank_id,
                    BankTransaction.transaction_id == event.transaction_id,
                )
            )
            if duplicate is not None:
                continue

            mapping = session.scalar(
                select(BankAccount).where(
                    BankAccount.bank_id == event.bank_id,
                    BankAccount.account_id == event.account_id,
                )
            )
            if mapping is None:
                mapping_for_customer = session.scalar(
                    select(BankAccount).where(
                        BankAccount.bank_id == event.bank_id,
                        BankAccount.customer_reference == event.customer_reference,
                    )
                )
                reason = (
                    "Account ID does not match the customer's mapped account"
                    if mapping_for_customer is not None
                    else "No mapped bank account for event"
                )
                _park_event(session, event, reason)
                continue
            if mapping.customer_reference != event.customer_reference:
                _park_event(
                    session,
                    event,
                    "Customer reference does not match the mapped account",
                )
                continue
            if event.currency != "EUR":
                _park_event(session, event, f"Unsupported currency: {event.currency}")
                continue
            if event.transfer_type != "credit" or event.status != "booked":
                _park_event(
                    session,
                    event,
                    f"Unsupported transfer type or status: "
                    f"{event.transfer_type}/{event.status}",
                )
                continue

            transaction_values: dict[str, object] = {
                "bank_account_id": mapping.id,
                "bank_id": event.bank_id,
                "account_id": event.account_id,
                "transaction_id": event.transaction_id,
                "customer_reference": event.customer_reference,
                "amount_minor": event.amount_minor,
                "currency": event.currency,
                "booked_balance_minor": event.booked_balance_minor,
                "account_version": event.account_version,
                "sequence": event.sequence,
                "occurred_at": event.occurred_at,
                "raw_payload": event.raw_payload,
            }
            inserted_id = session.execute(
                _insert_do_nothing(
                    session, BankTransaction, transaction_values
                ).on_conflict_do_nothing()
                .returning(BankTransaction.id)
            ).scalar_one_or_none()
            if inserted_id is None:
                continue

            session.add(
                OutboxEvent(
                    bank_transaction_id=inserted_id,
                    payload={
                        "bank_id": event.bank_id,
                        "account_id": event.account_id,
                        "customer_reference": event.customer_reference,
                        "transaction_id": event.transaction_id,
                        "amount_minor": event.amount_minor,
                        "currency": event.currency,
                    },
                )
            )

        cursor_insert = _insert_do_nothing(
            session,
            PollCursor,
            {"bank_id": bank_id, "cursor": next_cursor},
        )
        excluded_cursor = cursor_insert.excluded.cursor
        session.execute(
            cursor_insert.on_conflict_do_update(
                index_elements=[PollCursor.bank_id],
                set_={
                    "cursor": case(
                        (PollCursor.cursor < excluded_cursor, excluded_cursor),
                        else_=PollCursor.cursor,
                    ),
                    "updated_at": func.now(),
                },
            )
        )
