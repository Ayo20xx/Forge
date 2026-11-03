"""Normalize Polling Bank transaction events for Forge ingestion."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.services.bank_client import BankTransfer


@dataclass(frozen=True)
class Transfer:
    bank_id: str
    account_id: str
    customer_reference: str
    transaction_id: str
    amount_minor: int
    currency: str
    booked_balance_minor: int
    account_version: int
    sequence: int
    occurred_at: datetime
    raw_payload: dict[str, object]


class PollingAdapter:
    """Convert untrusted Polling Bank events to Forge's normalized transfer shape."""

    def adapt(self, event: BankTransfer) -> Transfer:
        if not isinstance(event, Mapping):
            raise ValueError("Polling Bank event must be an object")

        bank_id = self._required_string(event, "bank_id")
        account_id = self._required_string(event, "account_id")
        customer_reference = self._required_string(event, "customer_reference")
        transaction_id = self._required_string(event, "transaction_id")
        currency = self._required_string(event, "currency")
        amount_minor = self._required_integer(event, "amount_minor")
        booked_balance_minor = self._required_integer(event, "booked_balance_minor")
        account_version = self._required_integer(event, "account_version")
        sequence = self._required_integer(event, "sequence")
        occurred_at = self._occurred_at(event)

        if amount_minor <= 0:
            raise ValueError("Polling Bank transfer amount_minor must be positive")
        if account_version < 0 or sequence < 0:
            raise ValueError("Polling Bank event versions and sequence must be non-negative")

        return Transfer(
            bank_id=bank_id,
            account_id=account_id,
            customer_reference=customer_reference,
            transaction_id=transaction_id,
            amount_minor=amount_minor,
            currency=currency,
            booked_balance_minor=booked_balance_minor,
            account_version=account_version,
            sequence=sequence,
            occurred_at=occurred_at,
            raw_payload=dict(event),
        )

    @staticmethod
    def _required_string(event: Mapping[str, object], key: str) -> str:
        value = event.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Polling Bank event field {key} must be a non-empty string")
        return value

    @staticmethod
    def _required_integer(event: Mapping[str, object], key: str) -> int:
        value = event.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"Polling Bank event field {key} must be an integer")
        return value

    @staticmethod
    def _occurred_at(event: Mapping[str, object]) -> datetime:
        value = PollingAdapter._required_string(event, "occurred_at")
        try:
            occurred_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "Polling Bank event field occurred_at must be an ISO timestamp"
            ) from exc
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("Polling Bank event field occurred_at must include a timezone")
        return occurred_at
