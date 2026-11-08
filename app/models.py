# Defines normalized bank integration records and delivery state for Forge.

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


json_payload_type = JSON().with_variant(JSONB, "postgresql")


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("bank_id", "account_id", name="uq_bank_accounts_bank_account"),
        UniqueConstraint(
            "bank_id",
            "customer_reference",
            name="uq_bank_accounts_bank_customer_reference",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    iban: Mapped[str] = mapped_column(String(64), nullable=False)
    # Opaque reference owned by the core service; Forge does not interpret it.
    customer_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint(
            "bank_id", "transaction_id", name="uq_bank_transactions_bank_transaction"
        ),
        CheckConstraint("amount_minor > 0", name="ck_bank_transactions_positive_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id"), nullable=False
    )
    bank_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'EUR'")
    )
    # Bank snapshot for reconciliation only; it is never an amount to credit.
    booked_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_payload: Mapped[dict[str, object]] = mapped_column(json_payload_type, nullable=False)


class PollCursor(Base):
    __tablename__ = "poll_cursor"

    bank_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cursor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UnmappedTransaction(Base):
    __tablename__ = "unmapped_transactions"
    __table_args__ = (
        UniqueConstraint(
            "bank_id", "transaction_id", name="uq_unmapped_bank_transaction"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(json_payload_type, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("bank_transaction_id", name="uq_outbox_bank_transaction"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_outbox_events_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_outbox_events_nonnegative_attempts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("bank_transactions.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'balance.update'")
    )
    payload: Mapped[dict[str, object]] = mapped_column(json_payload_type, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
