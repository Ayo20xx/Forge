"""Build the Forge FastAPI app and manage its background Polling Bank worker."""

import asyncio
from collections.abc import AsyncIterator
from threading import Event, Thread

from fastapi import FastAPI

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import create_tables
from app.routers import admin, bank_accounts
from app.services.bank_client import PollingBankClient
from app.services.poller import run_poller


async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_tables(engine)
    stop_event = Event()
    bank_client = PollingBankClient()
    poller = Thread(
        target=run_poller,
        args=(
            bank_client,
            SessionLocal,
            get_settings().poll_interval_seconds,
            stop_event,
        ),
        name="forge-polling-bank",
        daemon=True,
    )
    try:
        poller.start()
        yield
    finally:
        stop_event.set()
        if poller.ident is not None:
            await asyncio.to_thread(poller.join)
        bank_client.close()


app = FastAPI(title="Forge", lifespan=lifespan)
app.include_router(admin.router)
app.include_router(bank_accounts.router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Report that the sandbox application process is responsive."""
    return {"ok": True, "sandbox": True}
