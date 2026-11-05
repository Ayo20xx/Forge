"""Persistence operations for bank accounts, ingestion, cursors, and outbox."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    BankAccount,
    BankTransaction,
    Base,
    OutboxEvent,
    PollCursor,
    UnmappedTransaction,
)
from app.schemas import BankAccountData, Transfer

logger = logging.getLogger(__name__)


class BankAccountConflict(Exception):
    """Raised when a bank account conflicts with an existing local mapping."""


class Repository:
    """Owns database queries and transaction boundaries for application services."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _insert_statement(
        session: Session, model: type[Base], values: dict[str, object]
    ) -> Any:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            return postgresql_insert(model).values(**values)
        if dialect == "sqlite":
            return sqlite_insert(model).values(**values)
        raise RuntimeError(f"Unsupported database dialect: {dialect}")

    @staticmethod
    def _save_bank_account(session: Session, account: BankAccountData) -> BankAccount:
        existing_by_id = session.scalar(
            select(BankAccount).where(
                BankAccount.bank_id == account.bank_id,
                BankAccount.account_id == account.account_id,
            )
        )
        existing_by_reference = session.scalar(
            select(BankAccount).where(
                BankAccount.bank_id == account.bank_id,
                BankAccount.customer_reference == account.customer_reference,
            )
        )

        if existing_by_id is not None:
            if (
                existing_by_id.customer_reference != account.customer_reference
                or existing_by_id.iban != account.iban
            ):
                raise BankAccountConflict(
                    "Bank account conflicts with its existing mapping"
                )
            return existing_by_id

        if existing_by_reference is not None:
            if (
                existing_by_reference.account_id != account.account_id
                or existing_by_reference.iban != account.iban
            ):
                raise BankAccountConflict(
                    "Customer reference conflicts with its existing bank account"
                )
            return existing_by_reference

        bank_account = BankAccount(
            bank_id=account.bank_id,
            account_id=account.account_id,
            iban=account.iban,
            customer_reference=account.customer_reference,
        )
        session.add(bank_account)
        session.flush()
        return bank_account

    def create_bank_account(self, account: BankAccountData) -> BankAccount:
        try:
            with self._session_factory.begin() as session:
                return self._save_bank_account(session, account)
        except IntegrityError as exc:
            raise BankAccountConflict(
                "Bank account conflicts with an existing mapping"
            ) from exc

    def sync_bank_accounts(
        self, accounts: Sequence[BankAccountData]
    ) -> list[BankAccount]:
        try:
            with self._session_factory.begin() as session:
                return [self._save_bank_account(session, account) for account in accounts]
        except IntegrityError as exc:
            raise BankAccountConflict(
                "Bank account conflicts with an existing mapping"
            ) from exc

    def find_bank_accounts(self, account_id: str) -> list[BankAccount]:
        with self._session_factory() as session:
            return session.scalars(
                select(BankAccount)
                .where(BankAccount.account_id == account_id)
                .limit(2)
            ).all()

    def stored_transaction_total(self, bank_account_id: int) -> int:
        with self._session_factory() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(BankTransaction.amount_minor), 0)).where(
                    BankTransaction.bank_account_id == bank_account_id
                )
            )
        return int(total or 0)

    def latest_cursor(self) -> tuple[str | None, int]:
        with self._session_factory() as session:
            row = session.execute(
                select(PollCursor.bank_id, PollCursor.cursor)
                .order_by(PollCursor.updated_at.desc())
                .limit(1)
            ).one_or_none()
        return (None, 0) if row is None else (row.bank_id, row.cursor)

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
                    self._insert_statement(session, BankTransaction, values)
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

            cursor_insert = self._insert_statement(
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

    def _park_event(
        self, session: Session, transfer: Transfer, reason: str
    ) -> None:
        values: dict[str, object] = {
            "bank_id": transfer.bank_id,
            "account_id": transfer.account_id,
            "transaction_id": transfer.transaction_id,
            "raw_payload": transfer.raw_payload,
            "reason": reason,
        }
        session.execute(
            self._insert_statement(session, UnmappedTransaction, values).on_conflict_do_nothing()
        )

    def publish_pending(
        self,
        send_event: Callable[[str, dict[str, object]], None],
        retry_error: type[Exception],
        now: datetime,
        batch_size: int,
    ) -> int:
        published_count = 0
        with self._session_factory.begin() as session:
            events = session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.status == "pending",
                    OutboxEvent.next_attempt_at <= now,
                )
                .order_by(OutboxEvent.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()
            for event in events:
                try:
                    send_event(event.event_type, event.payload)
                except retry_error:
                    event.attempts += 1
                    retry_seconds = min(2 ** min(event.attempts, 6), 60)
                    event.next_attempt_at = now + timedelta(seconds=retry_seconds)
                    logger.exception(
                        "Outbox event %s failed; retrying in %s seconds",
                        event.id,
                        retry_seconds,
                    )
                else:
                    event.status = "sent"
                    event.sent_at = now
                    published_count += 1
        return published_count
