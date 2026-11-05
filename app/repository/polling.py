"""Database operations for resuming the bank transaction poller."""

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import PollCursor


class PollingRepository:
    """Reads the saved bank-wide poll cursor."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def latest_cursor(self) -> tuple[str | None, int]:
        with self._session_factory() as session:
            row = session.execute(
                select(PollCursor.bank_id, PollCursor.cursor)
                .order_by(PollCursor.updated_at.desc())
                .limit(1)
            ).one_or_none()
        return (None, 0) if row is None else (row.bank_id, row.cursor)
