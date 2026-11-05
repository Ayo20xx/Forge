import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_repository
from app.main import app
from app.models import BankAccount, Base
from app.repository import Repository
from app.services.bank_client import BankError, PollingBankClient, get_bank_client


def account_data(
    *,
    account_id: str = "account-1",
    customer_reference: str = "customer-1",
    iban: str = "DE89370400440532013000",
) -> dict[str, object]:
    return {
        "bank_id": "polling-bank",
        "account_id": account_id,
        "customer_reference": customer_reference,
        "iban": iban,
        "currency": "EUR",
        "booked_balance_minor": 0,
        "available_balance_minor": 0,
        "account_version": 1,
        "sandbox": True,
    }


class FakeBankClient:
    def __init__(
        self,
        account: dict[str, object] | None = None,
        error: BankError | None = None,
    ) -> None:
        self.account = account or account_data()
        self.error = error
        self.created_references: list[str] = []

    def create_account(self, customer_reference: str) -> dict[str, object]:
        self.created_references.append(customer_reference)
        if self.error is not None:
            raise self.error
        return self.account


@pytest.fixture
def api_context(monkeypatch):
    monkeypatch.setattr("app.main.run_poller", lambda *args: None)
    monkeypatch.setattr("app.main.run_outbox_publisher", lambda *args: None)
    monkeypatch.setattr("app.main.upgrade_database", lambda: None)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = test_session_factory()
    repository = Repository(test_session_factory)
    bank_client = FakeBankClient()
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_bank_client] = lambda: bank_client

    try:
        yield TestClient(app), session, bank_client
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_post_bank_account_creates_at_bank_then_persists_mapping(api_context):
    client, session, bank_client = api_context

    response = client.post(
        "/bank-accounts",
        json={"customer_reference": "customer-1"},
    )

    assert response.status_code == 201
    assert response.json()["account_id"] == "account-1"
    assert response.json()["iban"] == "DE89370400440532013000"
    assert response.json()["customer_reference"] == "customer-1"
    assert bank_client.created_references == ["customer-1"]
    saved = session.scalar(select(BankAccount))
    assert saved is not None
    assert saved.account_id == "account-1"
    assert saved.iban == "DE89370400440532013000"


def test_post_bank_account_does_not_persist_when_bank_fails(api_context):
    client, session, bank_client = api_context
    bank_client.error = BankError("bank unavailable")

    response = client.post(
        "/bank-accounts",
        json={"customer_reference": "customer-1"},
    )

    assert response.status_code == 502
    assert session.scalar(select(func.count()).select_from(BankAccount)) == 0
    assert bank_client.created_references == ["customer-1"]


def test_post_bank_account_rejects_conflicting_existing_mapping(api_context):
    client, session, bank_client = api_context
    session.add(
        BankAccount(
            bank_id="polling-bank",
            account_id="account-existing",
            iban="DE89370400440532013000",
            customer_reference="customer-1",
        )
    )
    session.commit()
    bank_client.account = account_data(account_id="account-different")

    response = client.post(
        "/bank-accounts",
        json={"customer_reference": "customer-1"},
    )

    assert response.status_code == 409
    assert session.scalar(select(func.count()).select_from(BankAccount)) == 1
    saved = session.scalar(select(BankAccount))
    assert saved is not None
    assert saved.account_id == "account-existing"


def test_post_bank_account_is_idempotent_for_same_bank_mapping(api_context):
    client, session, _ = api_context
    body = {"customer_reference": "customer-1"}

    first = client.post("/bank-accounts", json=body)
    second = client.post("/bank-accounts", json=body)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert session.scalar(select(func.count()).select_from(BankAccount)) == 1


@pytest.mark.parametrize(
    "customer_reference",
    ["", "contains spaces", "customer/1", "x" * 65],
)
def test_post_bank_account_rejects_invalid_customer_reference(
    api_context, customer_reference
):
    client, session, bank_client = api_context

    response = client.post(
        "/bank-accounts",
        json={"customer_reference": customer_reference},
    )

    assert response.status_code == 422
    assert session.scalar(select(func.count()).select_from(BankAccount)) == 0
    assert bank_client.created_references == []


@pytest.mark.parametrize(
    "response_payload",
    [
        {"bank_id": "polling-bank", "account_id": "account-1"},
        {
            "bank_id": "polling-bank",
            "account_id": "account-1",
            "customer_reference": "different-customer",
            "iban": "DE89370400440532013000",
        },
    ],
)
def test_polling_bank_client_rejects_invalid_create_account_response(response_payload):
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    with PollingBankClient(
        base_url="https://bank.example",
        api_key="test-key",
        transport=httpx.MockTransport(respond),
    ) as bank_client:
        with pytest.raises(BankError):
            bank_client.create_account("customer-1")
