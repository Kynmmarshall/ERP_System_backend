import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PrincipalResponse(BaseModel):
    """Reflects the verified JWT claims - proves this service independently
    validated the token itself rather than trusting gateway headers alone."""

    user_id: str
    tenant_id: str | None
    campus_id: str | None
    role: str


class FeeScheduleCreateRequest(BaseModel):
    program_id: uuid.UUID
    term_id: uuid.UUID
    amount_xaf: int = Field(ge=0)


class FeeScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    term_id: uuid.UUID
    amount_xaf: int


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    enrollment_id: uuid.UUID
    student_id: uuid.UUID
    amount_xaf: int
    status: str
    created_at: datetime


class PaymentIntentCreateRequest(BaseModel):
    payer_msisdn: str = Field(min_length=8, max_length=20)


class PaymentIntentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    amount_xaf: int
    provider: str
    provider_reference: str
    redirect_url: str | None
    status: str
    created_at: datetime


class PaymentCallbackRequest(BaseModel):
    """Deliberately minimal - only the reference is trusted enough to look
    up which intent to re-check; every other field (including any status
    the caller supplies) is ignored, see app/routers/payments.py."""

    reference: str


class ReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    payment_intent_id: uuid.UUID
    amount_xaf: int
    issued_at: datetime


class ExpenseCreateRequest(BaseModel):
    category: str
    amount_xaf: int = Field(ge=0)
    description: str


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    amount_xaf: int
    description: str
    recorded_by: uuid.UUID
    created_at: datetime


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    posting_id: uuid.UUID
    entry_type: str
    direction: str
    amount_xaf: int
    reference_type: str
    reference_id: uuid.UUID
    description: str
    created_at: datetime


class CampaignCreateRequest(BaseModel):
    name: str
    cost_xaf: int = Field(ge=0, default=0)
    starts_on: date
    ends_on: date


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    cost_xaf: int
    starts_on: date
    ends_on: date


class LeadCreateRequest(BaseModel):
    campaign_id: uuid.UUID


class LeadConvertRequest(BaseModel):
    student_id: uuid.UUID


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    status: str
    student_id: uuid.UUID | None


class CampaignRoiResponse(BaseModel):
    campaign_id: uuid.UUID
    cost_xaf: int
    attributed_revenue_xaf: int
    roi: float | None
    roi_unavailable_reason: str | None


class FinancialSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period: date
    version: int
    total_revenue_xaf: int
    total_expenses_xaf: int
    net_xaf: int
    generated_at: datetime


class SummaryRegenerateRequest(BaseModel):
    period: date
