"""Pydantic models for API requests and bank integration payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class BankTransferEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    bank_id: str = Field(min_length=1, max_length=64)
    account_id: str = Field(min_length=1, max_length=128)
    customer_reference: str = Field(min_length=1, max_length=128)
    iban: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    booked_balance_minor: int = Field(strict=True)
    available_balance_minor: int = Field(strict=True)
    sandbox: bool = Field(strict=True)
    id: str
    transaction_id: str = Field(min_length=1, max_length=128)
    type: str
    status: str
    amount_minor: int = Field(gt=0, strict=True)
    account_version: int = Field(ge=0, strict=True)
    sequence: int = Field(ge=0, strict=True)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class TransactionPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    bank_id: str = Field(min_length=1, max_length=64)
    data: list[BankTransferEvent]
    next_cursor: int = Field(ge=0, strict=True)
    has_more: bool = Field(strict=True)


class Transfer(BaseModel):
    """Normalized bank transfer used by ingestion and the repository."""

    bank_id: str
    account_id: str
    customer_reference: str
    transaction_id: str
    amount_minor: int = Field(gt=0, strict=True)
    currency: str
    transfer_type: str
    status: str
    booked_balance_minor: int
    account_version: int = Field(ge=0, strict=True)
    sequence: int = Field(ge=0, strict=True)
    occurred_at: datetime
    raw_payload: dict[str, object]

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value

    @classmethod
    def from_bank_event(cls, event: BankTransferEvent) -> Transfer:
        return cls(
            bank_id=event.bank_id,
            account_id=event.account_id,
            customer_reference=event.customer_reference,
            transaction_id=event.transaction_id,
            amount_minor=event.amount_minor,
            currency=event.currency,
            transfer_type=event.type,
            status=event.status,
            booked_balance_minor=event.booked_balance_minor,
            account_version=event.account_version,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            raw_payload=event.model_dump(mode="json"),
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
