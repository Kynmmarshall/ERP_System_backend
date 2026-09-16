import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PrincipalResponse(BaseModel):
    """Reflects the verified JWT claims - proves this service independently
    validated the token itself rather than trusting gateway headers alone."""

    user_id: str
    tenant_id: str | None
    role: str


# --- Recruitment ---


class PositionCreateRequest(BaseModel):
    title: str
    department: str


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    department: str
    status: str
    created_at: datetime


class CandidateCreateRequest(BaseModel):
    position_id: uuid.UUID
    full_name: str
    email: str


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position_id: uuid.UUID
    full_name: str
    email: str
    stage: str
    created_at: datetime


class CandidateStageUpdateRequest(BaseModel):
    stage: str


class HireRequest(BaseModel):
    department: str
    gross_monthly_salary_xaf: int = Field(ge=0)
    hire_date: date


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    candidate_id: uuid.UUID | None
    full_name: str
    email: str
    department: str
    hire_date: date
    gross_monthly_salary_xaf: int
    status: str
    created_at: datetime


# --- Attendance ---


class ShiftCreateRequest(BaseModel):
    employee_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime


class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    created_at: datetime


class QRTokenResponse(BaseModel):
    token: str
    expires_at: datetime


class CheckInRequest(BaseModel):
    token: str


class AttendanceRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shift_id: uuid.UUID
    employee_id: uuid.UUID
    checked_in_at: datetime


# --- Leave ---


class LeaveRequestCreateRequest(BaseModel):
    starts_on: date
    ends_on: date
    reason: str


class LeaveRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    starts_on: date
    ends_on: date
    reason: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


class LeaveDecisionRequest(BaseModel):
    approve: bool


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    message: str
    notified_via_email: bool
    created_at: datetime
    read_at: datetime | None


# --- Performance ---


class PerformanceReviewCreateRequest(BaseModel):
    employee_id: uuid.UUID
    period: date
    rating: int = Field(ge=1, le=5)
    comments: str


class PerformanceReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    reviewer_id: uuid.UUID
    period: date
    rating: int
    comments: str
    created_at: datetime


# --- Assets ---


class AssetCreateRequest(BaseModel):
    name: str
    category: str
    total_quantity: int = Field(ge=0)


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    total_quantity: int
    created_at: datetime


class AssetMovementCreateRequest(BaseModel):
    asset_id: uuid.UUID
    employee_id: uuid.UUID | None = None
    quantity_delta: int
    reason: str


class AssetMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    employee_id: uuid.UUID | None
    quantity_delta: int
    reason: str
    created_at: datetime


# --- Payroll ---


class IrppBracket(BaseModel):
    up_to_xaf: int | None
    rate: Decimal


class PayrollScheduleCreateRequest(BaseModel):
    effective_from: date
    cnps_employee_rate: Decimal
    cnps_employer_rate: Decimal
    cnps_ceiling_xaf: int = Field(ge=0)
    standard_deduction_rate: Decimal
    irpp_brackets: list[IrppBracket]


class PayrollScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    effective_from: date
    is_verified: bool
    cnps_employee_rate: Decimal
    cnps_employer_rate: Decimal
    cnps_ceiling_xaf: int
    standard_deduction_rate: Decimal
    irpp_brackets: list[dict]
    created_at: datetime


class PayrollRunCreateRequest(BaseModel):
    period: date
    schedule_version_id: uuid.UUID


class PayrollRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period: date
    schedule_version_id: uuid.UUID
    status: str
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime


class PayslipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    employee_id: uuid.UUID
    period: date
    gross_xaf: int
    cnps_employee_xaf: int
    cnps_employer_xaf: int
    taxable_base_xaf: int
    irpp_xaf: int
    net_xaf: int
    created_at: datetime
