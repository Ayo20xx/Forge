# Creates the SQLAlchemy engine and session factory for connecting to Postgres.

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DEFAULT_DATABASE_URL = "postgresql+psycopg://forge:forge@localhost:5432/forge"

engine = create_engine(
    os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
