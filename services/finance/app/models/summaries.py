import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FinancialSummary(Base):
    """period is always the first day of the month it summarizes.
    Regeneration inserts a NEW row with version+1 - it never overwrites,
    so history/versioning is real (see phase5-plan.md).
    """

    __tablename__ = "financial_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    total_revenue_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_expenses_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_financial_summaries_institution_id", "institution_id"),
        UniqueConstraint("institution_id", "period", "version", name="uq_financial_summaries_period_version"),
    )
