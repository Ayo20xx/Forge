# Implements persistence and reconciliation services for external bank accounts.

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BankAccount, BankTransaction
from app.services.bank_client import BankAccount as BankAccountData


class BankAccountConflict(Exception):
    """Raised when a bank account conflicts with an existing local mapping."""


def _account_values(account: BankAccountData) -> dict[str, object]:
    return {
        "bank_id": account["bank_id"],
        "account_id": account["account_id"],
        "iban": account["iban"],
        "customer_reference": account["customer_reference"],
    }


def save_bank_account(session: Session, account: BankAccountData) -> BankAccount:
    """Persist an account unless its bank identity or opaque reference conflicts."""
    values = _account_values(account)
    existing_by_id = session.scalar(
        select(BankAccount).where(
            BankAccount.bank_id == account["bank_id"],
            BankAccount.account_id == account["account_id"],
        )
    )
    existing_by_reference = session.scalar(
        select(BankAccount).where(
            BankAccount.bank_id == account["bank_id"],
            BankAccount.customer_reference == account["customer_reference"],
        )
    )

    if existing_by_id is not None:
        if (
            existing_by_id.customer_reference != account["customer_reference"]
            or existing_by_id.iban != account["iban"]
        ):
            raise BankAccountConflict("Bank account conflicts with its existing mapping")
        return existing_by_id

    if existing_by_reference is not None:
        if (
            existing_by_reference.account_id != account["account_id"]
            or existing_by_reference.iban != account["iban"]
        ):
            raise BankAccountConflict(
                "Customer reference conflicts with its existing bank account"
            )
        return existing_by_reference

    bank_account = BankAccount(**values)
    session.add(bank_account)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise BankAccountConflict("Bank account conflicts with an existing mapping") from exc
    return bank_account


def sync_bank_accounts(
    session: Session, accounts: list[BankAccountData]
) -> list[BankAccount]:
    """Import known bank accounts atomically and idempotently."""
    try:
        imported = [save_bank_account(session, account) for account in accounts]
        session.commit()
    except Exception:
        session.rollback()
        raise
    return imported


def create_bank_account(
    session: Session, account: BankAccountData
) -> BankAccount:
    """Store a bank-created account, committing one local mapping."""
    try:
        bank_account = save_bank_account(session, account)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return bank_account


def get_stored_transaction_total(session: Session, bank_account: BankAccount) -> int:
    """Sum normalized transaction amounts; bank snapshots are not credits."""
    stored_total = session.scalar(
        select(func.coalesce(func.sum(BankTransaction.amount_minor), 0)).where(
            BankTransaction.bank_account_id == bank_account.id
        )
    )
    return int(stored_total or 0)


def sync_accounts_service(session:Session):
    pass

