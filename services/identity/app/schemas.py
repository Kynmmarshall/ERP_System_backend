import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.identity import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    institution_id: uuid.UUID | None
    campus_id: uuid.UUID | None
