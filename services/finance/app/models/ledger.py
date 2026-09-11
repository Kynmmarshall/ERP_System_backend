import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LedgerEntryType(str, enum.Enum):
    CASH = "cash"
    TUITION_REVENUE = "tuition_revenue"
    EXPENSE = "expense"


class LedgerDirection(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class LedgerEntry(Base):
    """Every real posting is >=2 rows sharing one posting_id with
    sum(debit amounts) == sum(credit amounts) - enforced in application
    code (see app/ledger.py._post_balanced), not a DB constraint (Postgres
    has no native way to check balance across an arbitrary row set).
    Immutable: no update/delete path exists, only new postings.
    """

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    posting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entry_type: Mapped[LedgerEntryType] = mapped_column(Enum(LedgerEntryType, name="ledger_entry_type"), nullable=False)
    direction: Mapped[LedgerDirection] = mapped_column(Enum(LedgerDirection, name="ledger_direction"), nullable=False)
    amount_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ledger_entries_institution_id", "institution_id"),
        Index("ix_ledger_entries_posting_id", "posting_id"),
        CheckConstraint("amount_xaf >= 0", name="ck_ledger_entries_amount_nonnegative"),
    )


class Receipt(Base):
    """Immutable - created exactly once, in the same transaction as the
    ledger posting, when a PaymentIntent reconciles to succeeded.
    """

    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_receipts_institution_id", "institution_id"),
        UniqueConstraint("invoice_id", name="uq_receipts_invoice"),
        CheckConstraint("amount_xaf >= 0", name="ck_receipts_amount_nonnegative"),
    )


class Expense(Base):
    """No update/delete endpoint exists - corrections are new, explicit,
    audited entries, never silent edits (see phase5-plan.md).
    """

    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_expenses_institution_id", "institution_id"),
        CheckConstraint("amount_xaf >= 0", name="ck_expenses_amount_nonnegative"),
    )
