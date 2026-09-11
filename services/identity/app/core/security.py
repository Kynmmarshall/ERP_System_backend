import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()

JWT_ISSUER = "ict-erp-identity"
JWT_AUDIENCE = "ict-erp-services"
JWT_ALGORITHM = "RS256"


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain_password)
    except VerifyMismatchError:
        return False


def _load_private_key() -> str:
    return Path(settings.jwt_private_key_path).read_text(encoding="utf-8")


def _load_public_key() -> str:
    return Path(settings.jwt_public_key_path).read_text(encoding="utf-8")


def issue_access_token(
    *,
    user_id: uuid.UUID,
    institution_id: uuid.UUID | None,
    campus_id: uuid.UUID | None,
    role: str,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "tenant_id": str(institution_id) if institution_id else None,
        "campus_id": str(campus_id) if campus_id else None,
        "role": role,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, _load_private_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired/tampered token."""
    return jwt.decode(
        token,
        _load_public_key(),
        algorithms=[JWT_ALGORITHM],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
    )


def generate_refresh_token() -> tuple[str, str]:
    """Returns (opaque_token_for_client, sha256_hash_for_storage)."""
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, token_hash


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
