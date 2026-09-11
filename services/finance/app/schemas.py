import uuid
from datetime import datetime

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
