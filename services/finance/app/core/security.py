from pathlib import Path

import jwt

from app.core.config import settings

# Must match services/identity/app/core/security.py exactly - this service
# independently verifies every token itself rather than trusting the gateway
# alone, per the defense-in-depth requirement.
JWT_ISSUER = "ict-erp-identity"
JWT_AUDIENCE = "ict-erp-services"
JWT_ALGORITHM = "RS256"


def _load_public_key() -> str:
    return Path(settings.jwt_public_key_path).read_text(encoding="utf-8")


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired/tampered token."""
    return jwt.decode(
        token,
        _load_public_key(),
        algorithms=[JWT_ALGORITHM],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
    )
