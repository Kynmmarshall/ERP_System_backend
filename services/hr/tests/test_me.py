"""/me proves this service verifies JWTs itself. Tokens are minted here using
the SAME dev private key identity uses (JWT_PRIVATE_KEY_PATH_FOR_TESTS env
var), never by importing identity's code.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER
from app.main import app


def _private_key() -> str:
    path = os.environ["JWT_PRIVATE_KEY_PATH_FOR_TESTS"]
    return Path(path).read_text(encoding="utf-8")


def _mint_token(*, expires_delta: timedelta = timedelta(minutes=10), **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": "admin",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    return jwt.encode(claims, _private_key(), algorithm=JWT_ALGORITHM)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_me_returns_principal_for_valid_token(client) -> None:
    user_id = str(uuid.uuid4())
    token = _mint_token(sub=user_id, role="staff")

    response = await client.get("/api/v1/hr/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user_id
    assert body["role"] == "staff"


async def test_me_rejects_missing_token(client) -> None:
    response = await client.get("/api/v1/hr/me")
    assert response.status_code == 401


async def test_me_rejects_expired_token(client) -> None:
    token = _mint_token(expires_delta=timedelta(minutes=-10))
    response = await client.get("/api/v1/hr/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_me_rejects_wrong_audience(client) -> None:
    token = _mint_token(aud="some-other-audience")
    response = await client.get("/api/v1/hr/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
