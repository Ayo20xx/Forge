# Defines validated API shapes so business rules can be implemented separately.

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UserResponse(BaseModel):
    id: int
    name: str
    customer_reference: str
    account_id: str | None = None
    iban: str | None = None


class AdminSyncResponse(BaseModel):
    imported_accounts: int


class BalanceResponse(BaseModel):
    user_id: int
    ledger_balance_minor: int
    bank_balance_minor: int
    matches: bool


class TransferCreate(BaseModel):
    from_user_id: int
    to_user_id: int
    # Amounts are integer EUR cents; never use floating-point values.
    amount_minor: int = Field(gt=0)


class TransferResponse(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    amount_minor: int
    idempotency_key: str

