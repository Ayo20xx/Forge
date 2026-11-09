# Provides the endpoint that imports accounts already present at the bank.

from fastapi import APIRouter, Depends

from app.routers.dependencies import get_bank_account_service
from app.schemas.admin import SyncResponse
from app.services.bank_accounts import BankAccountService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/sync", response_model=SyncResponse)
def sync_accounts(
    service: BankAccountService = Depends(get_bank_account_service),
) -> SyncResponse:
    accounts = service.sync_accounts()
    return SyncResponse(imported_count=len(accounts), accounts=accounts)
