"""Application settings loaded from environment variables and an optional .env file."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    polling_api_key: str
    bank_base_url: str
    database_url: str


def get_settings() -> Settings:
    return Settings(
        polling_api_key=os.getenv("POLLING_API_KEY", ""),
        bank_base_url=os.getenv(
            "BANK_BASE_URL",
            "https://bank-integration-lab.openaigoogle.workers.dev",
        ),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./tallybank.db"),
    )
