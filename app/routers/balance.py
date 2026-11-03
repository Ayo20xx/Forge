# Defines the balance endpoint placeholder for ledger and bank reconciliation.

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.bank_client import PollingBankClient, get_bank_client
from app.db import get_session
from app.schemas import BalanceResponse

router = APIRouter(prefix="/users", tags=["balances"])


@router.get("/{user_id}/balance", response_model=BalanceResponse)
def get_user_balance(
    user_id: int,
    session: Session = Depends(get_session),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> BalanceResponse:
    """TODO: compare the ledger sum with the bank-reported account balance.

    Balance is SUM(ledger_entries.amount_minor), in integer cents. Compare it
    only with the account's booked_balance_minor; never add bank balance fields
    to the ledger. Return 404 for an unknown user.
    """
    raise NotImplementedError
