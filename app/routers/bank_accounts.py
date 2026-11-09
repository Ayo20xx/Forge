# Provides account creation and reconciliation endpoints for bank integrations.

from fastapi import APIRouter, Depends

from app.routers.dependencies import get_bank_account_service
from app.schemas.bank_accounts import (
    BankAccountCreate,
    BankAccountResponse,
    ReconciliationResponse,
)
from app.services.bank_accounts import BankAccountService

router = APIRouter(prefix="/bank-accounts", tags=["bank accounts"])


@router.post("", response_model=BankAccountResponse, status_code=201)
def post_bank_account(
    body: BankAccountCreate,
    service: BankAccountService = Depends(get_bank_account_service),
) -> BankAccountResponse:
    return service.create_bank_account(body.customer_reference)


@router.get("/{account_id}/reconciliation", response_model=ReconciliationResponse)
def reconcile_bank_account(
    account_id: str,
    service: BankAccountService = Depends(get_bank_account_service),
) -> ReconciliationResponse:
    result = service.reconcile_bank_account(account_id)
    return ReconciliationResponse(
        account_id=result.account_id,
        stored_total_minor=result.stored_total_minor,
        bank_balance_minor=result.bank_balance_minor,
        difference_minor=result.difference_minor,
        matches=result.matches,
    )
