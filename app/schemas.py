# Defines validated request and response shapes for the bank integration API.

from pydantic import BaseModel, Field


class BankAccountCreate(BaseModel):
    customer_reference: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class BankAccountResponse(BaseModel):
    id: int
    bank_id: str
    account_id: str
    iban: str
    customer_reference: str

    model_config = {"from_attributes": True}


class SyncResponse(BaseModel):
    imported_count: int
    accounts: list[BankAccountResponse]


class ReconciliationResponse(BaseModel):
    account_id: str
    stored_total_minor: int
    bank_balance_minor: int
    difference_minor: int
    matches: bool
