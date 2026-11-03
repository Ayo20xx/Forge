# Provides the endpoint that imports accounts already present at the bank.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.bank_client import BankError, PollingBankClient, get_bank_client
from app.db import get_session
from app.schemas import BankAccountResponse, SyncResponse
from app.services import BankAccountConflict, sync_bank_accounts

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/sync", response_model=SyncResponse)
def sync_accounts(
    session: Session = Depends(get_session),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> SyncResponse:
    """Import existing bank accounts without interpreting their core references."""
    try:
        accounts = bank_client.list_accounts()
        imported = sync_bank_accounts(session, accounts)
    except BankError as exc:
        raise HTTPException(status_code=502, detail="Bank account sync failed") from exc
    except BankAccountConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SyncResponse(
        imported_count=len(imported),
        accounts=[BankAccountResponse.model_validate(account) for account in imported],
    )
