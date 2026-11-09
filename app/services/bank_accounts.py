"""Bank account business operations."""

from dataclasses import dataclass

from app.repository.bank_accounts import BankAccountConflict, BankAccountRepository
from app.schemas.admin import SyncResponse
from app.schemas.bank_accounts import (
    BankAccountCreate,
    BankAccountData,
    BankAccountResponse,
    ReconciliationResponse,
)
from app.services.bank_client import BankError, PollingBankClient


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


@dataclass(slots=True)
class BankAccountService:
    """Orchestrates business operations for bank accounts."""

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
            raise BankUnavailable("Bank account creation failed") from exc
        except BankAccountConflict as exc:
            raise BankAccountConflictError(str(exc)) from exc

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
            raise BankUnavailable("Bank account sync failed") from exc
        except BankAccountConflict as exc:
            raise BankAccountConflictError(str(exc)) from exc

        return SyncResponse(
            imported_count=len(imported),
            accounts=[BankAccountResponse.model_validate(account) for account in imported],
        )

    def reconcile_bank_account(self, account_id: str) -> ReconciliationResponse:
        """Compare stored transaction total with the bank's current booked balance."""
        bank_accounts = self.repository.find_bank_accounts(account_id)
        if not bank_accounts:
            raise BankAccountNotFound("Bank account not found")
        if len(bank_accounts) > 1:
            raise BankAccountAmbiguous("Account ID is ambiguous across banks")
        bank_account = bank_accounts[0]

        try:
            bank_snapshot = BankAccountData.model_validate(
                self.bank_client.get_balance(bank_account.account_id)
            )
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
        return ReconciliationResponse(
            account_id=bank_account.account_id,
            stored_total_minor=stored_total,
            bank_balance_minor=bank_total,
            difference_minor=bank_total - stored_total,
            matches=stored_total == bank_total,
        )
