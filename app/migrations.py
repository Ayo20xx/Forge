"""Alembic migration entry point used during application startup."""

from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_database_url


def upgrade_database() -> None:
    """Apply all checked-in Alembic migrations before serving requests."""
    project_root = Path(__file__).resolve().parent.parent
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", get_database_url().replace("%", "%%"))
    command.upgrade(config, "head")
