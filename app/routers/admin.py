# Provides the endpoint that imports accounts already present at the bank.

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_bank_account_repository
from app.repository.bank_accounts import BankAccountConflict, BankAccountRepository
from app.schemas.admin import SyncResponse
from app.schemas.bank_accounts import BankAccountData, BankAccountResponse
from app.services.bank_client import BankError, PollingBankClient, get_bank_client

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/sync", response_model=SyncResponse)
def sync_accounts(
    repository: BankAccountRepository = Depends(get_bank_account_repository),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> SyncResponse:
    """Import existing bank accounts without interpreting their core references."""
    try:
        accounts = [
            BankAccountData.model_validate(account)
            for account in bank_client.list_accounts()
        ]
        imported = repository.sync_bank_accounts(accounts)
    except BankError as exc:
        raise HTTPException(status_code=502, detail="Bank account sync failed") from exc
    except BankAccountConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SyncResponse(
        imported_count=len(imported),
        accounts=[BankAccountResponse.model_validate(account) for account in imported],
    )
