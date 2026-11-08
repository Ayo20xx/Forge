"""Shared SQL helpers for service-specific repositories."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import Base


def insert_statement(
    session: Session, model: type[Base], values: dict[str, object]
) -> Any:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(model).values(**values)
    if dialect == "sqlite":
        return sqlite_insert(model).values(**values)
    raise RuntimeError(f"Unsupported database dialect: {dialect}")
