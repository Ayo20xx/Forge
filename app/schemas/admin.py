"""Schemas for administrative bank-account synchronization."""

from pydantic import BaseModel

from app.schemas.bank_accounts import BankAccountResponse


class SyncResponse(BaseModel):
    imported_count: int
    accounts: list[BankAccountResponse]
