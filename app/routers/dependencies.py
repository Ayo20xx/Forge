"""FastAPI dependencies shared by the HTTP routes."""

from collections.abc import Generator

from fastapi import Depends

from app.db import get_bank_account_repository
from app.repository.bank_accounts import BankAccountRepository
from app.services.bank_accounts import BankAccountService
from app.services.bank_client import PollingBankClient


def get_bank_client() -> Generator[PollingBankClient, None, None]:
    """Create and close a Polling Bank client for an HTTP request."""
    with PollingBankClient() as client:
        yield client


def get_bank_account_service(
    repository: BankAccountRepository = Depends(get_bank_account_repository),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> BankAccountService:
    """Build the account service from route dependencies."""
    return BankAccountService(repository=repository, bank_client=bank_client)
