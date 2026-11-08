"""SQLAlchemy engine, session factory, and repository dependency."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_database_url
from app.repository.bank_accounts import BankAccountRepository

engine = create_engine(get_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_bank_account_repository() -> Generator[BankAccountRepository, None, None]:
    yield BankAccountRepository(SessionLocal)
