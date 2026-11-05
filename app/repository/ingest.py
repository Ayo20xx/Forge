"""Database operations for atomic transaction ingestion."""

from collections.abc import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    BankAccount,
    BankTransaction,
    OutboxEvent,
    PollCursor,
    UnmappedTransaction,
)
from app.repository._utils import insert_statement
from app.schemas.transactions import Transfer


class IngestionRepository:
    """Persists imported transactions, parked events, outbox rows, and cursor."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ingest_batch(
        self,
        transfers: Sequence[Transfer],
        next_cursor: int,
        bank_id: str,
    ) -> None:
        with self._session_factory.begin() as session:
            for transfer in transfers:
                duplicate = session.scalar(
                    select(BankTransaction.id).where(
                        BankTransaction.bank_id == transfer.bank_id,
                        BankTransaction.transaction_id == transfer.transaction_id,
                    )
                )
                if duplicate is not None:
                    continue

                mapping = session.scalar(
                    select(BankAccount).where(
                        BankAccount.bank_id == transfer.bank_id,
                        BankAccount.account_id == transfer.account_id,
                    )
                )
                if mapping is None:
                    mapped_customer = session.scalar(
                        select(BankAccount).where(
                            BankAccount.bank_id == transfer.bank_id,
                            BankAccount.customer_reference
                            == transfer.customer_reference,
                        )
                    )
                    reason = (
                        "Account ID does not match the customer's mapped account"
                        if mapped_customer is not None
                        else "No mapped bank account for event"
                    )
                    self._park_event(session, transfer, reason)
                    continue
                if mapping.customer_reference != transfer.customer_reference:
                    self._park_event(
                        session,
                        transfer,
                        "Customer reference does not match the mapped account",
                    )
                    continue
                if transfer.currency != "EUR":
                    self._park_event(
                        session, transfer, f"Unsupported currency: {transfer.currency}"
                    )
                    continue
                if transfer.transfer_type != "credit" or transfer.status != "booked":
                    self._park_event(
                        session,
                        transfer,
                        "Unsupported transfer type or status: "
                        f"{transfer.transfer_type}/{transfer.status}",
                    )
                    continue

                values: dict[str, object] = {
                    "bank_account_id": mapping.id,
                    "bank_id": transfer.bank_id,
                    "account_id": transfer.account_id,
                    "transaction_id": transfer.transaction_id,
                    "customer_reference": transfer.customer_reference,
                    "amount_minor": transfer.amount_minor,
                    "currency": transfer.currency,
                    "booked_balance_minor": transfer.booked_balance_minor,
                    "account_version": transfer.account_version,
                    "sequence": transfer.sequence,
                    "occurred_at": transfer.occurred_at,
                    "raw_payload": transfer.raw_payload,
                }
                inserted_id = session.execute(
                    insert_statement(session, BankTransaction, values)
                    .on_conflict_do_nothing()
                    .returning(BankTransaction.id)
                ).scalar_one_or_none()
                if inserted_id is None:
                    continue

                session.add(
                    OutboxEvent(
                        bank_transaction_id=inserted_id,
                        payload={
                            "bank_id": transfer.bank_id,
                            "account_id": transfer.account_id,
                            "customer_reference": transfer.customer_reference,
                            "transaction_id": transfer.transaction_id,
                            "amount_minor": transfer.amount_minor,
                            "currency": transfer.currency,
                        },
                    )
                )

            cursor_insert = insert_statement(
                session, PollCursor, {"bank_id": bank_id, "cursor": next_cursor}
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

    @staticmethod
    def _park_event(session: Session, transfer: Transfer, reason: str) -> None:
        values: dict[str, object] = {
            "bank_id": transfer.bank_id,
            "account_id": transfer.account_id,
            "transaction_id": transfer.transaction_id,
            "raw_payload": transfer.raw_payload,
            "reason": reason,
        }
        session.execute(
            insert_statement(session, UnmappedTransaction, values).on_conflict_do_nothing()
        )
