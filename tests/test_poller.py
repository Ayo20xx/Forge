from collections.abc import Generator
from threading import Event

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, PollCursor
from app.repository.ingest import IngestionRepository
from app.repository.polling import PollingRepository
from app.schemas.transactions import TransactionPage
from app.services.bank_client import BankError
from app.services.transaction_ingestion import (
    TransactionIngestionService,
    TransactionSource,
)
from app.workers.poller import run_poller

BANK_ID = "polling-bank"


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
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


class StopAfterWait:
    def __init__(self, stop_after: int) -> None:
        self.stop_after = stop_after
        self.waits: list[float] = []
        self.stopped = False

    def is_set(self) -> bool:
        return self.stopped

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        if len(self.waits) >= self.stop_after:
            self.stopped = True
        return self.stopped


class FakeBank(TransactionSource):
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.after_values: list[int] = []

    def get_transactions(self, *, after: int) -> TransactionPage:
        self.after_values.append(after)
        return parse_page(self.pages.pop(0))


def parse_page(payload: dict[str, object]) -> TransactionPage:
    try:
        return TransactionPage.model_validate(payload)
    except ValueError as exc:
        raise BankError("invalid test response") from exc


def page(next_cursor: int, *, has_more: bool) -> TransactionPage:
    return parse_page(
        {
            "bank_id": BANK_ID,
            "data": [],
            "next_cursor": next_cursor,
            "has_more": has_more,
        }
    )


def save_cursor(session_factory, cursor: int) -> None:
    with session_factory() as session:
        session.add(PollCursor(bank_id=BANK_ID, cursor=cursor))
        session.commit()


def read_cursor(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(PollCursor.cursor).where(PollCursor.bank_id == BANK_ID))


def test_poll_once_resumes_from_cursor_and_drains_all_pages(
    session_factory: sessionmaker[Session],
):
    save_cursor(session_factory, 5)
    bank = FakeBank([page(9, has_more=True), page(12, has_more=False)])
    service = TransactionIngestionService(
        ingestion_repository=IngestionRepository(session_factory),
        polling_repository=PollingRepository(session_factory),
        bank_client=bank,
    )

    assert service.poll_once()
    assert not service.poll_once()

    assert bank.after_values == [5, 9]
    assert read_cursor(session_factory) == 12


def test_poll_once_can_retry_bank_error_without_advancing_cursor(
    session_factory: sessionmaker[Session],
):
    class FailingOnceBank(TransactionSource):
        after_values: list[int] = []

        def get_transactions(self, *, after: int) -> TransactionPage:
            self.after_values.append(after)
            if len(self.after_values) == 1:
                raise BankError("temporary failure")
            return page(4, has_more=False)

    bank = FailingOnceBank()
    service = TransactionIngestionService(
        ingestion_repository=IngestionRepository(session_factory),
        polling_repository=PollingRepository(session_factory),
        bank_client=bank,
    )

    with pytest.raises(BankError, match="temporary failure"):
        service.poll_once()
    assert read_cursor(session_factory) is None
    assert not service.poll_once()

    assert bank.after_values == [0, 0]
    assert read_cursor(session_factory) == 4


def test_poller_caps_retry_backoff_at_sixty_seconds():
    class AlwaysFailingService:
        def poll_once(self) -> bool:
            raise BankError("bank unavailable")

    stop = StopAfterWait(8)
    run_poller(
        AlwaysFailingService(),
        stop_event=stop,
    )

    assert stop.waits == [1, 2, 4, 8, 16, 32, 60, 60]


def test_poller_stops_between_pages():
    stop = Event()

    class StopAfterFirstPage:
        calls = 0

        def poll_once(self) -> bool:
            self.calls += 1
            stop.set()
            return True

    service = StopAfterFirstPage()
    run_poller(service, stop_event=stop)

    assert service.calls == 1


@pytest.mark.parametrize(
    "invalid_page",
    [
        {"bank_id": BANK_ID, "data": [], "next_cursor": 0, "has_more": True},
        {"bank_id": BANK_ID, "data": [], "next_cursor": -1, "has_more": False},
        {"bank_id": BANK_ID, "data": [], "next_cursor": 1, "has_more": "broken"},
        {"bank_id": "different-bank", "data": [], "next_cursor": 1, "has_more": False},
    ],
)
def test_poll_once_rejects_invalid_pages_without_advancing_cursor(
    session_factory: sessionmaker[Session], invalid_page: dict[str, object]
):
    save_cursor(session_factory, 0)

    class InvalidThenValidBank(TransactionSource):
        calls = 0

        def get_transactions(self, *, after: int) -> TransactionPage:
            assert after == 0
            self.calls += 1
            return parse_page(invalid_page) if self.calls == 1 else page(3, has_more=False)

    bank = InvalidThenValidBank()
    service = TransactionIngestionService(
        ingestion_repository=IngestionRepository(session_factory),
        polling_repository=PollingRepository(session_factory),
        bank_client=bank,
    )

    with pytest.raises((ValueError, BankError)):
        service.poll_once()
    assert read_cursor(session_factory) == 0
    assert not service.poll_once()

    assert read_cursor(session_factory) == 3


def test_poller_rejects_non_positive_interval(
    session_factory: sessionmaker[Session],
):
    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        run_poller(
            TransactionIngestionService(
                ingestion_repository=IngestionRepository(session_factory),
                polling_repository=PollingRepository(session_factory),
                bank_client=FakeBank([]),
            ),
            interval_seconds=0,
            stop_event=Event(),
        )
