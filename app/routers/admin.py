# Provides the endpoint that imports accounts already present at the bank.

from fastapi import APIRouter, Depends

from app.schemas.admin import SyncResponse
from app.services.workflows import BankAccountService, get_bank_account_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/sync", response_model=SyncResponse)
def sync_accounts(
    service: BankAccountService = Depends(get_bank_account_service),
) -> SyncResponse:
    return service.sync_accounts()
