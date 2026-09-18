import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InvoiceStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"


class FeeSchedule(Base):
    """Configured independently by finance (admin-only) - academic's
    program_id/term_id are trusted opaque references here too, the same way
    student_id is trusted from academic's own Enrollment (no cross-service FK).
    """

    __tablename__ = "fee_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    program_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_fee_schedules_institution_id", "institution_id"),
        UniqueConstraint("institution_id", "program_id", "term_id", name="uq_fee_schedules_program_term"),
        CheckConstraint("amount_xaf >= 0", name="ck_fee_schedules_amount_nonnegative"),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"), nullable=False, default=InvoiceStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_invoices_institution_id", "institution_id"),
        Index("ix_invoices_student_id", "student_id"),
        UniqueConstraint("institution_id", "enrollment_id", name="uq_invoices_enrollment"),
        CheckConstraint("amount_xaf >= 0", name="ck_invoices_amount_nonnegative"),
    )


class InboxEvent(Base):
    """Not RLS-protected - purely a cross-tenant idempotency ledger for the
    consumer; the same rationale as academic's OutboxEvent.
    """

    __tablename__ = "inbox_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
