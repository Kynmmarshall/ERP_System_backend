from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt

from app.core.config import settings

# Must match services/identity/app/core/security.py exactly - this service
# independently verifies every token itself rather than trusting the gateway
# alone, per the defense-in-depth requirement.
JWT_ISSUER = "ict-erp-identity"
JWT_AUDIENCE = "ict-erp-services"
JWT_ALGORITHM = "RS256"

# QR shift tokens are HR-internal only (issued and verified by this same
# service, never presented to any other service or used as an API access
# token) so a symmetric secret is used - a different audience/algorithm
# from the RS256 identity-issued access tokens above means a stolen QR
# token can never be replayed as a real API token and vice versa.
QR_TOKEN_AUDIENCE = "ict-erp-hr-qr"
QR_TOKEN_ALGORITHM = "HS256"


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


def issue_qr_token(*, shift_id: UUID, jti: UUID, expires_delta: timedelta = timedelta(minutes=10)) -> str:
    now = datetime.now(UTC)
    claims = {
        "shift_id": str(shift_id),
        "jti": str(jti),
        "aud": QR_TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(claims, settings.hr_qr_signing_secret, algorithm=QR_TOKEN_ALGORITHM)


def decode_qr_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired/tampered token."""
    return jwt.decode(token, settings.hr_qr_signing_secret, algorithms=[QR_TOKEN_ALGORITHM], audience=QR_TOKEN_AUDIENCE)
