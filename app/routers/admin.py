# Defines the admin sync endpoint placeholder for bank account import logic.

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.bank_client import PollingBankClient, get_bank_client
from app.db import get_session
from app.schemas import AdminSyncResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/sync", response_model=AdminSyncResponse)
def sync_accounts(
    session: Session = Depends(get_session),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> AdminSyncResponse:
    """TODO: import bank accounts as local users and bank-account mappings.

    Implement this idempotently; if the bank call fails, return HTTP 502 and
    leave local data unchanged. Never guess a user mapping. The sandbox has no
    authentication, so expose this only in the explicitly unauthenticated demo.
    """
    raise NotImplementedError
