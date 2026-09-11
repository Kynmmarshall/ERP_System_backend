import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PayrollRunStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"


class PayrollScheduleVersion(Base):
    """is_verified is the release gate: a PayrollRun can only be approved
    using a schedule version where this is true. The seeded schedule is
    deliberately is_verified=false - see phase6-plan.md for why (no
    official CNPS/DGI rates could be confirmed in this session; these
    values are illustrative/structural only, never a compliance claim).
    irpp_brackets is a JSONB list of {"up_to_xaf": int|null, "rate":
    float} rows, sorted ascending by up_to_xaf, last row's up_to_xaf=null
    meaning "and above".
    """

    __tablename__ = "payroll_schedule_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cnps_employee_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    cnps_employer_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    cnps_ceiling_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    standard_deduction_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    irpp_brackets: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_payroll_schedule_versions_institution_id", "institution_id"),)


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    schedule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_schedule_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PayrollRunStatus] = mapped_column(
        Enum(PayrollRunStatus, name="payroll_run_status"), nullable=False, default=PayrollRunStatus.DRAFT
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_payroll_runs_institution_id", "institution_id"),
        UniqueConstraint("institution_id", "period", name="uq_payroll_runs_period"),
    )


class Payslip(Base):
    """Immutable once its run is approved. The unique (institution_id,
    employee_id, period) constraint (period denormalized from the run) is
    what makes a repeated run-generation call for an already-covered
    period idempotent/rejected rather than a silent duplicate payment.
    """

    __tablename__ = "payslips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    gross_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cnps_employee_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cnps_employer_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    taxable_base_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    irpp_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_xaf: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_payslips_institution_id", "institution_id"),
        Index("ix_payslips_employee_id", "employee_id"),
        UniqueConstraint("institution_id", "employee_id", "period", name="uq_payslips_employee_period"),
        CheckConstraint("gross_xaf >= 0", name="ck_payslips_gross_nonnegative"),
    )
