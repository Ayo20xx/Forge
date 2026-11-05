"""Database operations for bank-account routes and reconciliation."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import BankAccount, BankTransaction
from app.schemas.bank_accounts import BankAccountData


class BankAccountConflict(Exception):
    """Raised when a bank account conflicts with an existing local mapping."""


class BankAccountRepository:
    """Owns persistence for bank-account mappings and their totals."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

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
