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
| API / services    | --> | Repository       | --> | PostgreSQL 16        |
| app/routers       |     | SQLAlchemy models|     | accounts, events,   |
| app/services     |     +------------------+     | cursors, outbox     |
+-------------------+                               +----------------------+
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

Create a local environment file and set the sandbox API key and service URLs:

```bash
cp .env.example .env
```

`POLLING_API_KEY`, `BANK_BASE_URL`, and `DATABASE_URL` are required. The
application has no embedded fallback URLs. For local development, the example
database URL points to `localhost`.

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

Polling Bank transaction events are validated and normalized by Pydantic models
in `app/schemas.py`. The normalized `Transfer` keeps the event amount separate
from the bank balance snapshot and retains the original event payload for auditing.
`ingest_batch` commits each page's mapped transactions, pending outbox messages,
parked events, and bank cursor as one transaction. Duplicate transaction IDs
are ignored, and only booked EUR credits are accepted for mapped accounts.
`app/repository.py` owns database queries and transaction boundaries. At
application startup, Forge applies Alembic migrations and starts a background
poller. It resumes the saved cursor, drains pages, waits 30 seconds between
successful polls, and backs off up to 60 seconds after failures.
The outbox publisher also starts at application startup. It sends due pending
events through `LoggingSender`, marks successful deliveries as sent, and
retries delivery errors with capped exponential delays.

## Docker setup

With `.env` populated, start both Postgres and the API. Since the sample
`DATABASE_URL` targets a host-run app, use the Compose service name `db` from
inside the container:

```bash
DATABASE_URL=postgresql+psycopg://forge:forge@db:5432/forge \
docker compose up --build
```

The API listens on port 8000, and Compose waits for Postgres's health check
before starting it. The container image excludes `.env`; Compose supplies its
values at runtime.

## Tests and lint

Run the test suite with:

```bash
python -m pip install -r requirements.txt
ruff check .
python -m pytest -q
```

The bank-account endpoint tests use isolated in-memory SQLite sessions and a
fake bank client. Polling Bank HTTP response validation uses
`httpx.MockTransport`; tests do not call the bank or require Postgres. Alembic
migrations are applied by the app at startup and can also be run with
`alembic upgrade head`.

## Polling Bank interface

`app/services/bank_client.py` follows the sandbox OpenAPI operations:

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
