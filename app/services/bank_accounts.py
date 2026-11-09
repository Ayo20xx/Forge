"""Bank account business operations."""

from dataclasses import dataclass
from typing import Protocol

from app.models import BankAccount
from app.repository.bank_accounts import BankAccountConflict, BankAccountRepository
from app.schemas.bank_accounts import BankAccountData
from app.services.bank_client import BankError


class BankGateway(Protocol):
    """Bank operations required by the bank-account service."""

    def create_account(self, customer_reference: str) -> BankAccountData: ...

    def list_accounts(self) -> list[BankAccountData]: ...

    def get_balance(self, account_id: str) -> BankAccountData: ...


class BankAccountNotFound(Exception):
    """Raised when no local mapping exists for the requested account."""


class BankAccountAmbiguous(Exception):
    """Raised when an account ID matches multiple local mappings."""


class BankUnavailable(Exception):
    """Raised when the bank cannot complete an account operation."""


class BankAccountMismatch(Exception):
    """Raised when the bank returns details for a different account."""


class BankAccountConflictError(Exception):
    """Raised when a bank account conflicts with an existing local mapping."""


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Comparison of the locally stored total and the bank's balance snapshot."""

    account_id: str
    stored_total_minor: int
    bank_balance_minor: int
    difference_minor: int
    matches: bool


@dataclass(slots=True)
class BankAccountService:
    """Orchestrates business operations for bank accounts."""

    repository: BankAccountRepository
    bank_client: BankGateway

    def create_bank_account(self, customer_reference: str) -> BankAccount:
        """Create an account at the bank and store its local mapping."""
        try:
            account = self.bank_client.create_account(customer_reference)
            saved = self.repository.create_bank_account(account)
        except BankError as exc:
            raise BankUnavailable("Bank account creation failed") from exc
        except BankAccountConflict as exc:
            raise BankAccountConflictError(str(exc)) from exc

        return saved

    def sync_accounts(self) -> list[BankAccount]:
        """Import existing bank accounts without interpreting their core references."""
        try:
            accounts = self.bank_client.list_accounts()
            imported = self.repository.sync_bank_accounts(accounts)
        except BankError as exc:
            raise BankUnavailable("Bank account sync failed") from exc
        except BankAccountConflict as exc:
            raise BankAccountConflictError(str(exc)) from exc

        return imported

    def reconcile_bank_account(self, account_id: str) -> ReconciliationResult:
        """Compare stored transaction total with the bank's current booked balance."""
        bank_accounts = self.repository.find_bank_accounts(account_id)
        if not bank_accounts:
            raise BankAccountNotFound("Bank account not found")
        if len(bank_accounts) > 1:
            raise BankAccountAmbiguous("Account ID is ambiguous across banks")
        bank_account = bank_accounts[0]

        try:
            bank_snapshot = self.bank_client.get_balance(bank_account.account_id)
        except BankError as exc:
            raise BankUnavailable("Bank balance request failed") from exc

        if (
            bank_snapshot.bank_id != bank_account.bank_id
            or bank_snapshot.account_id != bank_account.account_id
            or bank_snapshot.customer_reference != bank_account.customer_reference
        ):
            raise BankAccountMismatch("Bank returned a mismatched account")

        # booked_balance_minor is only a comparison snapshot, never a ledger credit.
        stored_total = self.repository.stored_transaction_total(bank_account.id)
        bank_total = bank_snapshot.booked_balance_minor
        return ReconciliationResult(
            account_id=bank_account.account_id,
            stored_total_minor=stored_total,
            bank_balance_minor=bank_total,
            difference_minor=bank_total - stored_total,
            matches=stored_total == bank_total,
        )
