# Provides typed HTTP plumbing for the simulated Polling Bank API.

from __future__ import annotations

from collections.abc import Generator
from typing import cast
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.schemas.bank_accounts import BankAccountData
from app.schemas.transactions import TransactionPage


class BankError(Exception):
    """Raised when a Polling Bank request fails or returns an invalid response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PollingBankClient:
    """Small synchronous client for the endpoints in the Polling Bank OpenAPI spec."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._client = httpx.Client(
            base_url=(base_url or settings.bank_base_url).rstrip("/"),
            headers={"X-API-Key": settings.polling_api_key if api_key is None else api_key},
            timeout=timeout,
            transport=transport,
        )

    def _request_json(
        self, method: str, path: str, **kwargs: object
    ) -> dict[str, object]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise BankError("Polling Bank request failed due to a transport error") from exc

        if not response.is_success:
            raise BankError(
                "Polling Bank returned a non-success status",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise BankError("Polling Bank returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise BankError("Polling Bank returned an unexpected response shape")
        return cast(dict[str, object], payload)

    def list_accounts(self) -> list[BankAccountData]:
        """Return all receiving accounts from GET /polling-bank/accounts."""
        payload = self._request_json("GET", "/polling-bank/accounts")
        accounts = payload.get("data")
        if not isinstance(accounts, list):
            raise BankError("Polling Bank returned an invalid accounts response")
        try:
            return [BankAccountData.model_validate(account) for account in accounts]
        except ValueError as exc:
            raise BankError("Polling Bank returned invalid account data") from exc

    def create_account(self, customer_reference: str) -> BankAccountData:
        """Create or retrieve the idempotent account for a customer reference."""
        payload = self._request_json(
            "POST",
            "/polling-bank/accounts",
            json={"customer_reference": customer_reference},
        )
        try:
            account = BankAccountData.model_validate(payload)
        except ValueError as exc:
            raise BankError("Polling Bank returned an invalid account response") from exc
        if account.customer_reference != customer_reference:
            raise BankError("Polling Bank returned an account for a different customer")
        return account

    def get_balance(self, account_id: str) -> BankAccountData:
        """Return the account snapshot from its balance endpoint."""
        path = f"/polling-bank/accounts/{quote(account_id, safe='')}/balance"
        try:
            return BankAccountData.model_validate(self._request_json("GET", path))
        except ValueError as exc:
            raise BankError("Polling Bank returned invalid balance data") from exc

    def get_transactions(self, after: int = 0) -> TransactionPage:
        """Return one bank-wide transaction page after the supplied sequence cursor."""
        if after < 0:
            raise ValueError("after cursor must be non-negative")
        try:
            return TransactionPage.model_validate(
                self._request_json(
                    "GET",
                    "/polling-bank/transactions",
                    params={"after": after},
                )
            )
        except ValueError as exc:
            raise BankError("Polling Bank returned an invalid transaction page") from exc

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> PollingBankClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def get_bank_client() -> Generator[PollingBankClient, None, None]:
    """FastAPI dependency that creates and closes a Polling Bank client."""
    with PollingBankClient() as client:
        yield client
