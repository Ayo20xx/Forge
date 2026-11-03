# Builds the Forge FastAPI app and exposes its working health check.

from fastapi import FastAPI

from app.routers import admin, bank_accounts

app = FastAPI(title="Forge")
app.include_router(admin.router)
app.include_router(bank_accounts.router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Report that the sandbox application process is responsive."""
    return {"ok": True, "sandbox": True}
