import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.identity import Role, RoleRequestStatus


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    """Public self-registration - always creates a STUDENT account; the role
    is never taken from the client. `requested_role` only records which
    dashboard the applicant is asking for, to be approved by an admin later
    (see app/routers/auth.py).
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    requested_role: Role | None = None
    justification: str = Field(default="", max_length=500)

    @field_validator("requested_role")
    @classmethod
    def _only_requestable_roles(cls, value: Role | None) -> Role | None:
        # SUPER_ADMIN is platform-level: allowing it here would let an
        # institution admin approve someone into platform-wide access, which
        # routers/users.py deliberately reserves for an existing super admin.
        if value is not None and value == Role.SUPER_ADMIN:
            raise ValueError("That role cannot be requested at registration")
        return value


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


class UserSummaryResponse(BaseModel):
    """Admin user-management view. Deliberately excludes password_hash and
    every other credential field."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class UserRoleUpdateRequest(BaseModel):
    role: Role


class RoleRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    requested_role: Role
    status: RoleRequestStatus
    justification: str
    decided_at: datetime | None
    created_at: datetime


class RoleRequestDecisionRequest(BaseModel):
    approve: bool
