"""Validated application configuration loaded from environment variables."""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError


class Settings(BaseModel):
    polling_api_key: str = Field(min_length=1)
    bank_base_url: str = Field(min_length=1)
    database_url: str = Field(min_length=1)
    poll_interval_seconds: int = Field(default=30, gt=0)


def _environment() -> dict[str, str | None]:
    load_dotenv()
    return {
        "polling_api_key": os.getenv("POLLING_API_KEY"),
        "bank_base_url": os.getenv("BANK_BASE_URL"),
        "database_url": os.getenv("DATABASE_URL"),
        "poll_interval_seconds": os.getenv("POLL_INTERVAL_SECONDS", "30"),
    }


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings.model_validate(_environment())
    except ValidationError as exc:
        raise RuntimeError(
            "Invalid configuration: set POLLING_API_KEY, BANK_BASE_URL, "
            "and DATABASE_URL; POLL_INTERVAL_SECONDS must be positive"
        ) from exc


@lru_cache
def get_database_url() -> str:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    return database_url
