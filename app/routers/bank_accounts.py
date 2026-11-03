# Provides account creation and reconciliation endpoints for bank integrations.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import BankAccount
from app.schemas import BankAccountCreate, BankAccountResponse, ReconciliationResponse
from app.services.bank_client import BankError, PollingBankClient, get_bank_client
from app.services.services import (
    BankAccountConflict,
    create_bank_account,
    get_stored_transaction_total,
)

router = APIRouter(prefix="/bank-accounts", tags=["bank accounts"])


@router.post("", response_model=BankAccountResponse, status_code=201)
def post_bank_account(
    body: BankAccountCreate,
    session: Session = Depends(get_session),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> BankAccountResponse:
    """Create the receiving account at the bank, then store its local mapping."""
    try:
        account = bank_client.create_account(body.customer_reference)
        saved = create_bank_account(session, account)
    except BankError as exc:
        raise HTTPException(status_code=502, detail="Bank account creation failed") from exc
    except BankAccountConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return BankAccountResponse.model_validate(saved)


@router.get("/{account_id}/reconciliation", response_model=ReconciliationResponse)
def reconcile_bank_account(
    account_id: str,
    session: Session = Depends(get_session),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> ReconciliationResponse:
    """Compare stored transaction total with the bank's current booked balance."""
    bank_accounts = session.scalars(
        select(BankAccount)
        .where(BankAccount.account_id == account_id)
        .limit(2)
    ).all()
    if not bank_accounts:
        raise HTTPException(status_code=404, detail="Bank account not found")
    if len(bank_accounts) > 1:
        raise HTTPException(
            status_code=409,
            detail="Account ID is ambiguous across banks",
        )
    bank_account = bank_accounts[0]

    try:
        bank_snapshot = bank_client.get_balance(bank_account.account_id)
    except BankError as exc:
        raise HTTPException(status_code=502, detail="Bank balance request failed") from exc

    if bank_snapshot["bank_id"] != bank_account.bank_id:
        raise HTTPException(status_code=502, detail="Bank returned a mismatched account")
    if bank_snapshot["account_id"] != bank_account.account_id:
        raise HTTPException(status_code=502, detail="Bank returned a mismatched account")
    if bank_snapshot["customer_reference"] != bank_account.customer_reference:
        raise HTTPException(status_code=502, detail="Bank returned a mismatched account")

    # booked_balance_minor is only a comparison snapshot, never a ledger credit.
    stored_total = get_stored_transaction_total(session, bank_account)
    bank_total = bank_snapshot["booked_balance_minor"]
    return ReconciliationResponse(
        account_id=bank_account.account_id,
        stored_total_minor=stored_total,
        bank_balance_minor=bank_total,
        difference_minor=bank_total - stored_total,
        matches=stored_total == bank_total,
    )
