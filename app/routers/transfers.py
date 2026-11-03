# Defines the internal transfer endpoint placeholder and its request contract.

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import TransferCreate, TransferResponse

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post("", response_model=TransferResponse)
def create_transfer(
    body: TransferCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1),
    session: Session = Depends(get_session),
) -> TransferResponse:
    """TODO: implement an atomic, idempotent internal ledger transfer.

    Write both append-only ledger rows and the transfer record in one database
    transaction; reject insufficient funds with 409 and same-user transfers
    with 400. Make concurrent spending safe, and store all money as integer cents.
    """
    raise NotImplementedError
