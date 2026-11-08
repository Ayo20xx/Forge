"""Build the Forge FastAPI app and manage its background Polling Bank worker."""

import asyncio
from collections.abc import AsyncIterator
from threading import Event, Thread

from fastapi import FastAPI

from app.config import get_settings
from app.db import SessionLocal
from app.migrations import upgrade_database
from app.repository.ingest import IngestionRepository
from app.repository.outbox import OutboxRepository
from app.repository.polling import PollingRepository
from app.routers import admin, bank_accounts
from app.services.bank_client import PollingBankClient
from app.services.workflows import LoggingSender, run_outbox_publisher, run_poller


async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    upgrade_database()
    stop_event = Event()
    bank_client = PollingBankClient()
    logging_sender = LoggingSender()
    polling_repository = PollingRepository(SessionLocal)
    ingestion_repository = IngestionRepository(SessionLocal)
    outbox_repository = OutboxRepository(SessionLocal)
    poller = Thread(
        target=run_poller,
        args=(
            bank_client,
            polling_repository,
            ingestion_repository,
            get_settings().poll_interval_seconds,
            stop_event,
        ),
        name="forge-polling-bank",
        daemon=True,
    )
    outbox_publisher = Thread(
        target=run_outbox_publisher,
        args=(outbox_repository, logging_sender, stop_event),
        name="forge-outbox-publisher",
        daemon=True,
    )
    try:
        poller.start()
        outbox_publisher.start()
        yield
    finally:
        stop_event.set()
        if poller.ident is not None:
            await asyncio.to_thread(poller.join)
        if outbox_publisher.ident is not None:
            await asyncio.to_thread(outbox_publisher.join)
        bank_client.close()


app = FastAPI(title="Forge", lifespan=lifespan)
app.include_router(admin.router)
app.include_router(bank_accounts.router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Report that the sandbox application process is responsive."""
    return {"ok": True, "sandbox": True}
