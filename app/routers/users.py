# Defines user endpoint placeholders for user and bank-account creation.

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.bank_client import PollingBankClient, get_bank_client
from app.db import get_session
from app.schemas import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse)
def create_user(
    body: UserCreate,
    session: Session = Depends(get_session),
    bank_client: PollingBankClient = Depends(get_bank_client),
) -> UserResponse:
    """TODO: persist a local user and create their receiving account at the bank.

    Generate a valid customer_reference, call create_account(), and save the
    bank account ID and IBAN. If the bank call fails, roll back the local user.
    """
    raise NotImplementedError


@router.get("", response_model=list[UserResponse])
def list_users(session: Session = Depends(get_session)) -> list[UserResponse]:
    """TODO: return local users with their mapped bank account details."""
    raise NotImplementedError
