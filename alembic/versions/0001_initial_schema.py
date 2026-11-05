"""Create the initial Forge integration schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_payload_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bank_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("iban", sa.String(length=64), nullable=False),
        sa.Column("customer_reference", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bank_id", "account_id", name="uq_bank_accounts_bank_account"
        ),
        sa.UniqueConstraint(
            "bank_id",
            "customer_reference",
            name="uq_bank_accounts_bank_customer_reference",
        ),
    )
    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=False),
        sa.Column("bank_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("customer_reference", sa.String(length=128), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'EUR'"), nullable=False),
        sa.Column("booked_balance_minor", sa.BigInteger(), nullable=False),
        sa.Column("account_version", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("raw_payload", json_payload_type, nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0", name="ck_bank_transactions_positive_amount"
        ),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bank_id",
            "transaction_id",
            name="uq_bank_transactions_bank_transaction",
        ),
    )
    op.create_table(
        "poll_cursor",
        sa.Column("bank_id", sa.String(length=64), nullable=False),
        sa.Column("cursor", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("bank_id"),
    )
    op.create_table(
        "unmapped_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bank_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("raw_payload", json_payload_type, nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bank_id", "transaction_id", name="uq_unmapped_bank_transaction"
        ),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bank_transaction_id", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=64),
            server_default=sa.text("'balance.update'"),
            nullable=False,
        ),
        sa.Column("payload", json_payload_type, nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_outbox_events_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_outbox_events_nonnegative_attempts"
        ),
        sa.ForeignKeyConstraint(
            ["bank_transaction_id"], ["bank_transactions.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bank_transaction_id", name="uq_outbox_bank_transaction"
        ),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("unmapped_transactions")
    op.drop_table("poll_cursor")
    op.drop_table("bank_transactions")
    op.drop_table("bank_accounts")
