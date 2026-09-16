import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaymentIntentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PaymentIntent(Base):
    """provider_reference is generated and persisted BEFORE any gateway call
    is made (see app/payments/) - it doubles as MTN's X-Reference-Id /
    idempotency key, so a crash between insert and the provider call just
    leaves a PENDING row the reconciliation poller retries against, never
    a duplicate charge. A partial unique index (see the migration) allows
    only one PENDING/SUCCEEDED intent per invoice at a time.
    """

    __tablename__ = "payment_intents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    amount_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="mtn_momo")
    provider_reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # Only set for hosted-redirect providers (camerpay): the provider's OWN
    # transaction id (distinct from provider_reference, which is OUR
    # idempotency key) and the URL to send the customer's browser to.
    # Direct push-to-phone providers (mtn_momo, test_double) leave both null.
    provider_transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    redirect_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payer_msisdn: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[PaymentIntentStatus] = mapped_column(
        Enum(PaymentIntentStatus, name="payment_intent_status"),
        nullable=False,
        default=PaymentIntentStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_payment_intents_institution_id", "institution_id"),
        Index("ix_payment_intents_invoice_id", "invoice_id"),
        Index("ix_payment_intents_status", "status"),
    )
