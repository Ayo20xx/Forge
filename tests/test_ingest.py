from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    BankAccount,
    BankTransaction,
    Base,
    OutboxEvent,
    PollCursor,
    UnmappedTransaction,
)
from app.repository import Repository
from app.schemas import BankTransferEvent, Transfer
from app.services.ingest import ingest_batch

BANK_ID = "polling-bank"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = test_session_factory()
    session.info["test_session_factory"] = test_session_factory
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def repository(db_session):
    return Repository(db_session.info["test_session_factory"])


def event_data(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "bank_id": BANK_ID,
        "account_id": "account-1",
        "customer_reference": "customer-1",
        "iban": "DE89370400440532013000",
        "currency": "EUR",
        "booked_balance_minor": 8000,
        "available_balance_minor": 8000,
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
    event.update(overrides)
    return event


def add_account(
    session: Session,
    *,
    account_id: str = "account-1",
    customer_reference: str = "customer-1",
) -> BankAccount:
    account = BankAccount(
        bank_id=BANK_ID,
        account_id=account_id,
        iban="DE89370400440532013000",
        customer_reference=customer_reference,
    )
    session.add(account)
    session.commit()
    return account


def count_rows(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_ingest_batch_persists_transaction_outbox_and_cursor_atomically(
    db_session, repository
):
    account = add_account(db_session)

    ingest_batch(repository, [event_data()], 42)

    transaction = db_session.scalar(select(BankTransaction))
    outbox = db_session.scalar(select(OutboxEvent))
    cursor = db_session.get(PollCursor, BANK_ID)
    assert transaction is not None
    assert transaction.bank_account_id == account.id
    assert transaction.amount_minor == 1250
    assert transaction.booked_balance_minor == 8000
    assert outbox is not None
    assert outbox.bank_transaction_id == transaction.id
    assert outbox.status == "pending"
    assert outbox.payload == {
        "bank_id": BANK_ID,
        "account_id": "account-1",
        "customer_reference": "customer-1",
        "transaction_id": "transaction-1",
        "amount_minor": 1250,
        "currency": "EUR",
    }
    assert cursor is not None
    assert cursor.cursor == 42


@pytest.mark.parametrize(
    ("event_overrides", "existing_account", "reason"),
    [
        ({}, False, "No mapped bank account for event"),
        (
            {"customer_reference": "different-customer"},
            True,
            "Customer reference does not match the mapped account",
        ),
        (
            {"account_id": "different-account"},
            True,
            "Account ID does not match the customer's mapped account",
        ),
        ({"currency": "USD"}, True, "Unsupported currency: USD"),
        ({"type": "debit"}, True, "Unsupported transfer type or status: debit/booked"),
        ({"status": "pending"}, True, "Unsupported transfer type or status: credit/pending"),
    ],
)
def test_ingest_batch_parks_unsafe_events(
    db_session, repository, event_overrides, existing_account, reason
):
    if existing_account:
        add_account(db_session)

    ingest_batch(repository, [event_data(**event_overrides)], 42)

    unmapped = db_session.scalar(select(UnmappedTransaction))
    cursor = db_session.get(PollCursor, BANK_ID)
    assert count_rows(db_session, BankTransaction) == 0
    assert count_rows(db_session, OutboxEvent) == 0
    assert unmapped is not None
    assert unmapped.reason == reason
    assert unmapped.raw_payload == event_data(**event_overrides)
    assert cursor is not None
    assert cursor.cursor == 42


def test_ingest_batch_skips_duplicate_transactions_and_outbox_rows(db_session, repository):
    add_account(db_session)
    event = event_data()

    ingest_batch(repository, [event, event], 42)
    ingest_batch(repository, [event], 42)

    assert count_rows(db_session, BankTransaction) == 1
    assert count_rows(db_session, OutboxEvent) == 1
    assert count_rows(db_session, UnmappedTransaction) == 0


def test_ingest_batch_deduplicates_repeated_unmapped_events(db_session, repository):
    event = event_data()

    ingest_batch(repository, [event, event], 42)
    ingest_batch(repository, [event], 42)

    assert count_rows(db_session, UnmappedTransaction) == 1
    assert count_rows(db_session, BankTransaction) == 0
    assert count_rows(db_session, OutboxEvent) == 0


def test_ingest_batch_supports_empty_pages_and_never_rewinds_cursor(db_session, repository):
    ingest_batch(repository, [], 42, bank_id=BANK_ID)
    ingest_batch(repository, [], 12, bank_id=BANK_ID)

    cursor = db_session.get(PollCursor, BANK_ID)
    assert cursor is not None
    assert cursor.cursor == 42


def test_ingest_batch_requires_bank_id_for_empty_pages(db_session, repository):
    with pytest.raises(ValueError, match="bank_id is required"):
        ingest_batch(repository, [], 42)

    assert count_rows(db_session, PollCursor) == 0


def test_ingest_batch_rolls_back_rows_and_cursor_on_database_error(db_session, repository):
    add_account(db_session)
    ingest_batch(repository, [], 10, bank_id=BANK_ID)
    transfer = Transfer.from_bank_event(BankTransferEvent.model_validate(event_data()))
    invalid_json_transfer = transfer.model_copy(
        update={"raw_payload": {"not_json": {1, 2}}}
    )

    with pytest.raises(StatementError):
        ingest_batch(repository, [invalid_json_transfer], 20)

    assert count_rows(db_session, BankTransaction) == 0
    assert count_rows(db_session, OutboxEvent) == 0
    cursor = db_session.get(PollCursor, BANK_ID)
    assert cursor is not None
    assert cursor.cursor == 10


def test_ingest_batch_rolls_back_transaction_when_outbox_insert_fails(
    db_session, repository
):
    add_account(db_session)
    ingest_batch(repository, [], 10, bank_id=BANK_ID)
    db_session.execute(
        text(
            "CREATE TRIGGER reject_outbox_insert BEFORE INSERT ON outbox_events "
            "BEGIN SELECT RAISE(ABORT, 'outbox unavailable'); END"
        )
    )
    db_session.commit()

    with pytest.raises(IntegrityError, match="outbox unavailable"):
        ingest_batch(repository, [event_data()], 20)

    assert count_rows(db_session, BankTransaction) == 0
    assert count_rows(db_session, OutboxEvent) == 0
    cursor = db_session.get(PollCursor, BANK_ID)
    assert cursor is not None
    assert cursor.cursor == 10


def test_transfer_occurrence_timestamp_is_timezone_aware():
    transfer = Transfer.from_bank_event(BankTransferEvent.model_validate(event_data()))

    assert transfer.occurred_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
