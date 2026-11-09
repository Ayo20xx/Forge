from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import BankAccount, BankTransaction, Base, OutboxEvent
from app.repository.outbox import OutboxRepository
from app.services.outbox_publisher import LoggingSender, SenderError, publish_pending

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def add_outbox_event(session_factory, *, next_attempt_at: datetime = NOW) -> int:
    with session_factory() as session:
        account = BankAccount(
            bank_id="polling-bank",
            account_id="account-1",
            iban="DE89370400440532013000",
            customer_reference="customer-1",
        )
        session.add(account)
        session.flush()
        transaction = BankTransaction(
            bank_account_id=account.id,
            bank_id="polling-bank",
            account_id="account-1",
            transaction_id="transaction-1",
            customer_reference="customer-1",
            amount_minor=1250,
            currency="EUR",
            booked_balance_minor=9000,
            account_version=1,
            sequence=1,
            occurred_at=NOW,
            raw_payload={"amount_minor": 1250},
        )
        session.add(transaction)
        session.flush()
        event = OutboxEvent(
            bank_transaction_id=transaction.id,
            payload={"transaction_id": "transaction-1", "amount_minor": 1250},
            next_attempt_at=next_attempt_at,
        )
        session.add(event)
        session.commit()
        return event.id


def read_event(session_factory, event_id: int) -> OutboxEvent:
    with session_factory() as session:
        return session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def test_publisher_sends_due_event_and_marks_it_sent(session_factory, caplog):
    caplog.set_level("INFO")
    event_id = add_outbox_event(session_factory)

    published = publish_pending(OutboxRepository(session_factory), LoggingSender(), now=NOW)

    event = read_event(session_factory, event_id)
    assert published == 1
    assert event.status == "sent"
    assert as_utc(event.sent_at) == NOW
    assert event.attempts == 0
    assert "Published outbox event balance.update" in caplog.text


def test_publisher_keeps_future_events_pending(session_factory):
    event_id = add_outbox_event(session_factory, next_attempt_at=NOW + timedelta(seconds=1))

    published = publish_pending(OutboxRepository(session_factory), LoggingSender(), now=NOW)

    event = read_event(session_factory, event_id)
    assert published == 0
    assert event.status == "pending"


def test_publisher_schedules_retry_after_sender_failure(session_factory, caplog):
    event_id = add_outbox_event(session_factory)

    class FailingSender:
        def send(self, event_type: str, payload: dict[str, object]) -> None:
            raise SenderError("temporary sender failure")

    published = publish_pending(OutboxRepository(session_factory), FailingSender(), now=NOW)

    event = read_event(session_factory, event_id)
    assert published == 0
    assert event.status == "pending"
    assert event.attempts == 1
    assert as_utc(event.next_attempt_at) == NOW + timedelta(seconds=2)
    assert "Outbox event" in caplog.text


def test_publisher_does_not_swallow_unexpected_sender_errors(session_factory):
    event_id = add_outbox_event(session_factory)

    class BrokenSender:
        def send(self, event_type: str, payload: dict[str, object]) -> None:
            raise RuntimeError("unexpected failure")

    with pytest.raises(RuntimeError, match="unexpected failure"):
        publish_pending(OutboxRepository(session_factory), BrokenSender(), now=NOW)

    event = read_event(session_factory, event_id)
    assert event.status == "pending"
    assert event.attempts == 0


def test_publisher_retries_with_capped_exponential_delay(session_factory):
    event_id = add_outbox_event(session_factory)

    class FailingSender:
        def send(self, event_type: str, payload: dict[str, object]) -> None:
            raise SenderError("temporary sender failure")

    for attempts in range(1, 7):
        current_time = as_utc(read_event(session_factory, event_id).next_attempt_at)
        publish_pending(OutboxRepository(session_factory), FailingSender(), now=current_time)
        event = read_event(session_factory, event_id)
        assert event.attempts == attempts
        delay = min(2**attempts, 60)
        assert as_utc(event.next_attempt_at) == current_time + timedelta(seconds=delay)


@pytest.mark.parametrize("batch_size", [0, -1])
def test_publisher_rejects_non_positive_batch_size(session_factory, batch_size):
    with pytest.raises(ValueError, match="batch_size must be positive"):
        publish_pending(
            OutboxRepository(session_factory),
            LoggingSender(),
            now=NOW,
            batch_size=batch_size,
        )


def test_publisher_requires_timezone_aware_now(session_factory):
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        publish_pending(
            OutboxRepository(session_factory),
            LoggingSender(),
            now=datetime(2026, 1, 2, 3, 4, 5),
        )
