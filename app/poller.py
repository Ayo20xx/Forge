# Defines the background poll-loop contract for resumable Polling Bank ingestion.

from sqlalchemy.orm import Session, sessionmaker

from app.bank_client import PollingBankClient


def run_poller(
    bank_client: PollingBankClient,
    session_factory: sessionmaker[Session],
    interval_seconds: int = 30,
) -> None:
    """TODO: repeatedly fetch and atomically ingest all available bank pages.

    Resume from the stored bank-wide cursor; keep requesting pages while
    has_more is true. Do not advance the cursor after any bank or DB failure.
    Retry failures with exponential backoff capped at 60 seconds, and use the
    configured polling interval between successful batches.
    """
    raise NotImplementedError
