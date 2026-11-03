# Forge

Forge is a sandbox project for a Wise-style, multi-customer euro ledger. It
connects local customer records to simulated receiving accounts at the Polling
Bank and prepares the database, HTTP client, and test harness for implementing
the ledger business logic.

## Architecture

```text
                         +----------------------+
                         | Polling Bank sandbox |
                         +----------+-----------+
                                    | HTTP / X-API-Key
                                    v
+-------------------+     +--------+---------+     +----------------------+
| API / future logic| --> | SQLAlchemy layer | --> | PostgreSQL 16        |
| app/routers       |     | models + sessions|     | users, accounts,     |
| app/ingest.py     |     +------------------+     | ledger, cursors      |
| app/poller.py     |                               +----------------------+
+-------------------+
```

## Domain rules

- Money is an integer number of EUR cents (`amount_minor`); never use floats.
- Only an event's `amount_minor` is a credit. Never add
  `booked_balance_minor` or `available_balance_minor` to the ledger.
- Deduplicate bank deposits using the database unique constraint on
  `(bank_id, transaction_id)`.
- Persist ledger rows and the poll cursor in one database transaction. On a
  bank error, retry with backoff and do not advance the cursor.
- Ledger entries are append-only. A user's balance is
  `SUM(ledger_entries.amount_minor)`.
- Unknown or conflicting bank accounts go to `unmapped_transactions`; never
  guess which user owns them.
- **No authentication yet; sandbox only.** Do not use this app for real money or
  real customer information.

## Local setup

Create a local environment file and fill in the sandbox API key privately:

```bash
cp .env.example .env
```

Install dependencies and start PostgreSQL:

```bash
python -m pip install -r requirements.txt
docker compose up -d db
```

Run the API locally:

```bash
uvicorn app.main:app --reload
```

The health endpoint is `http://localhost:8000/health`. The integration routes
create a bank account, import existing bank accounts, and reconcile a stored
transaction total with the bank's current booked balance:

- `POST /bank-accounts` with a core-owned `customer_reference`
- `POST /admin/sync`
- `GET /bank-accounts/{account_id}/reconciliation`

The customer reference is an opaque identifier passed through from the core
service; Forge does not create or own a customer record.

## Docker setup

With `.env` populated, start both Postgres and the API:

```bash
docker compose up --build
```

The API listens on port 8000, and Compose waits for Postgres's health check
before starting it. The container image excludes `.env`; Compose supplies its
values at runtime.

## Tests and lint

Start the local Postgres service first, then run:

```bash
python -m pip install -r requirements.txt
ruff check .
pytest -q
```

Database tests create a separate `forge_test` database using the configured
Postgres connection, and drop only that database when the test session ends.
They refuse to overwrite a pre-existing `forge_test`. Tests never call the
Polling Bank over the network: HTTP behavior uses `httpx.MockTransport`, and
the API fixture uses a scriptable fake bank client. Skipped tests describe
business behavior that is intentionally left for you to implement.

## Polling Bank interface

`app/bank_client.py` follows the sandbox OpenAPI operations:

- `GET` and `POST /polling-bank/accounts`
- `GET /polling-bank/accounts/{account_id}/balance`
- `GET /polling-bank/transactions?after=<cursor>`

Requests send `X-API-Key`; the client uses a timeout and raises `BankError` for
transport failures, non-2xx responses, and malformed JSON. The transaction
cursor is bank-wide, and pages must be drained while `has_more` is true.

## Next: Webhook Bank

The simulator also documents a Webhook Bank integration. Add it only after the
Polling Bank ledger path is working: verify webhook signatures against the exact
raw request bytes, reject stale timestamps, persist before acknowledging, and
deduplicate events with the same `(bank_id, transaction_id)` key. Never treat a
webhook balance snapshot as a ledger credit.
