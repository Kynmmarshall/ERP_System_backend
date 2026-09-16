import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.identity import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    """Public self-registration - always creates a STUDENT account; role is
    never accepted from the client (see app/routers/auth.py)."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    mfa_required: bool = False


class MfaChallengeResponse(BaseModel):
    """Returned by /login instead of tokens when the account's role requires
    MFA. Carries no credential material - the code only ever goes to the
    account's own email."""

    mfa_required: bool = True
    challenge_id: uuid.UUID
    expires_in_seconds: int


class MfaVerifyRequest(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    institution_id: uuid.UUID | None
    campus_id: uuid.UUID | None


class UserSummaryResponse(BaseModel):
    """Admin user-management view. Deliberately excludes password_hash and
    every other credential field."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    campus_id: uuid.UUID | None
    created_at: datetime


class UserRoleUpdateRequest(BaseModel):
    role: Role
