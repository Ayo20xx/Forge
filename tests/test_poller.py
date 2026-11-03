from threading import Event

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, PollCursor
from app.services.bank_client import BankError
from app.services.poller import run_poller

BANK_ID = "polling-bank"


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


class FakeBank:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.after_values: list[int] = []

    def get_transactions(self, *, after: int) -> dict[str, object]:
        self.after_values.append(after)
        return self.pages.pop(0)


def page(next_cursor: int, *, has_more: bool) -> dict[str, object]:
    return {
        "bank_id": BANK_ID,
        "data": [],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def save_cursor(session_factory, cursor: int) -> None:
    with session_factory() as session:
        session.add(PollCursor(bank_id=BANK_ID, cursor=cursor))
        session.commit()


def read_cursor(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(PollCursor.cursor).where(PollCursor.bank_id == BANK_ID))


def test_poller_resumes_from_cursor_and_drains_all_pages(session_factory):
    save_cursor(session_factory, 5)
    bank = FakeBank([page(9, has_more=True), page(12, has_more=False)])
    stop = StopAfterWait(1)

    run_poller(bank, session_factory, interval_seconds=30, stop_event=stop)

    assert bank.after_values == [5, 9]
    assert read_cursor(session_factory) == 12
    assert stop.waits == [30]


def test_poller_retries_bank_errors_with_exponential_backoff(session_factory):
    class FailingOnceBank:
        after_values: list[int] = []

        def get_transactions(self, *, after: int) -> dict[str, object]:
            self.after_values.append(after)
            if len(self.after_values) == 1:
                raise BankError("temporary failure")
            return page(4, has_more=False)

    bank = FailingOnceBank()
    stop = StopAfterWait(2)

    run_poller(bank, session_factory, interval_seconds=30, stop_event=stop)

    assert bank.after_values == [0, 0]
    assert stop.waits == [1, 30]
    assert read_cursor(session_factory) == 4


def test_poller_caps_retry_backoff_at_sixty_seconds(session_factory):
    class AlwaysFailingBank:
        def get_transactions(self, *, after: int) -> dict[str, object]:
            raise BankError("bank unavailable")

    stop = StopAfterWait(8)
    run_poller(AlwaysFailingBank(), session_factory, stop_event=stop)

    assert stop.waits == [1, 2, 4, 8, 16, 32, 60, 60]


@pytest.mark.parametrize(
    ("invalid_page", "message"),
    [
        ({"bank_id": BANK_ID, "data": [], "next_cursor": 0, "has_more": True}, "did not advance"),
        ({"bank_id": BANK_ID, "data": [], "next_cursor": -1, "has_more": False}, "next_cursor"),
        ({"bank_id": BANK_ID, "data": [], "next_cursor": 1, "has_more": 0}, "has_more"),
        (
            {"bank_id": "different-bank", "data": [], "next_cursor": 1, "has_more": False},
            "identity",
        ),
    ],
)
def test_poller_retries_invalid_pages_without_advancing_cursor(
    session_factory, invalid_page, message
):
    save_cursor(session_factory, 0)

    class InvalidThenValidBank:
        calls = 0

        def get_transactions(self, *, after: int) -> dict[str, object]:
            self.calls += 1
            return invalid_page if self.calls == 1 else page(3, has_more=False)

    bank = InvalidThenValidBank()
    stop = StopAfterWait(2)

    run_poller(bank, session_factory, stop_event=stop)

    assert read_cursor(session_factory) == 3
    assert stop.waits == [1, 30]


def test_poller_rejects_non_positive_interval(session_factory):
    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        run_poller(FakeBank([]), session_factory, interval_seconds=0, stop_event=Event())
