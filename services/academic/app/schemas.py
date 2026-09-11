import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PrincipalResponse(BaseModel):
    """Reflects the verified JWT claims - proves this service independently
    validated the token itself rather than trusting gateway headers alone."""

    user_id: str
    tenant_id: str | None
    campus_id: str | None
    role: str


class ProgramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str


class TermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starts_on: datetime
    ends_on: datetime


class EnrollmentCreateRequest(BaseModel):
    program_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID
    # Staff/admin may enroll a specific student; a student may only enroll themselves.
    student_id: uuid.UUID | None = None


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID
    student_id: uuid.UUID
    status: str
    created_at: datetime
