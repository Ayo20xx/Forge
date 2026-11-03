from datetime import UTC, datetime

import pytest

from app.services.adapter import PollingAdapter, Transfer


@pytest.fixture
def bank_event() -> dict[str, object]:
    return {
        "bank_id": "polling-bank",
        "account_id": "account-1",
        "customer_reference": "customer-1",
        "iban": "DE89370400440532013000",
        "currency": "EUR",
        "booked_balance_minor": 9000,
        "available_balance_minor": 9000,
        "sandbox": True,
        "id": "event-1",
        "transaction_id": "transaction-1",
        "type": "credit",
        "status": "booked",
        "amount_minor": 1250,
        "account_version": 1,
        "sequence": 42,
        "occurred_at": "2026-01-02T03:04:05Z",
    }


def test_polling_adapter_normalizes_bank_event(bank_event):
    transfer = PollingAdapter().adapt(bank_event)

    assert transfer == Transfer(
        bank_id="polling-bank",
        account_id="account-1",
        customer_reference="customer-1",
        transaction_id="transaction-1",
        amount_minor=1250,
        currency="EUR",
        transfer_type="credit",
        status="booked",
        booked_balance_minor=9000,
        account_version=1,
        sequence=42,
        occurred_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        raw_payload=bank_event,
    )
    assert transfer.amount_minor == 1250
    assert transfer.amount_minor != bank_event["booked_balance_minor"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bank_id", ""),
        ("account_id", None),
        ("customer_reference", 1),
        ("transaction_id", ""),
        ("currency", None),
        ("amount_minor", True),
        ("booked_balance_minor", "1250"),
        ("account_version", 1.5),
        ("sequence", None),
        ("occurred_at", "not-a-timestamp"),
        ("occurred_at", "2026-01-02T03:04:05"),
        ("amount_minor", 0),
        ("amount_minor", -1),
        ("account_version", -1),
        ("sequence", -1),
    ],
)
def test_polling_adapter_rejects_invalid_event_fields(bank_event, field, value):
    bank_event[field] = value

    with pytest.raises(ValueError):
        PollingAdapter().adapt(bank_event)
