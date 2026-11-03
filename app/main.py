# Builds the Forge FastAPI app and exposes its working health check.

from fastapi import FastAPI

from app.routers import admin, balance, transfers, users

app = FastAPI(title="Forge")
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(balance.router)
app.include_router(transfers.router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Report that the sandbox application process is responsive."""
    return {"ok": True, "sandbox": True}
