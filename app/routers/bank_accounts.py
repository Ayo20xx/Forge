# Provides account creation and reconciliation endpoints for bank integrations.

from fastapi import APIRouter, Depends

from app.schemas.bank_accounts import (
    BankAccountCreate,
    BankAccountResponse,
    ReconciliationResponse,
)
from app.services.bank_accounts import BankAccountService, get_bank_account_service

router = APIRouter(prefix="/bank-accounts", tags=["bank accounts"])


@router.post("", response_model=BankAccountResponse, status_code=201)
def post_bank_account(
    body: BankAccountCreate,
    service: BankAccountService = Depends(get_bank_account_service),
) -> BankAccountResponse:
    return service.create_bank_account(body)


@router.get("/{account_id}/reconciliation", response_model=ReconciliationResponse)
def reconcile_bank_account(
    account_id: str,
    service: BankAccountService = Depends(get_bank_account_service),
) -> ReconciliationResponse:
    return service.reconcile_bank_account(account_id)
