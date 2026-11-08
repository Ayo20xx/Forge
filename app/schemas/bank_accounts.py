"""Schemas for bank-account creation and reconciliation."""

from pydantic import BaseModel, ConfigDict, Field


class BankAccountCreate(BaseModel):
    customer_reference: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class BankAccountData(BaseModel):
    model_config = ConfigDict(extra="allow")

    bank_id: str = Field(min_length=1, max_length=64)
    account_id: str = Field(min_length=1, max_length=128)
    customer_reference: str = Field(min_length=1, max_length=128)
    iban: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    booked_balance_minor: int = Field(strict=True)
    available_balance_minor: int = Field(strict=True)
    account_version: int = Field(ge=0, strict=True)
    sandbox: bool = Field(strict=True)


class BankAccountResponse(BaseModel):
    id: int
    bank_id: str
    account_id: str
    iban: str
    customer_reference: str

    model_config = ConfigDict(from_attributes=True)


class ReconciliationResponse(BaseModel):
    account_id: str
    stored_total_minor: int
    bank_balance_minor: int
    difference_minor: int
    matches: bool
