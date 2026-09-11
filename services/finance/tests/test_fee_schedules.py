"""Fee-schedule and invoice REST endpoint tests. Require a real, migrated
Postgres reachable via DATABASE_URL (see readme.md) - these exercise real
RLS, not a mocked DB layer.
"""
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import SessionFactory
from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER
from app.core.tenant_context import set_platform_context
from app.main import app
from app.models.finance import FeeSchedule


def _private_key() -> str:
    path = os.environ["JWT_PRIVATE_KEY_PATH_FOR_TESTS"]
    return Path(path).read_text(encoding="utf-8")


def _mint_token(*, expires_delta: timedelta = timedelta(minutes=10), **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "campus_id": None,
        "role": "student",
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


async def test_admin_can_create_fee_schedule(client) -> None:
    institution_id = uuid.uuid4()
    token = _mint_token(tenant_id=str(institution_id), role="admin")

    response = await client.post(
        "/api/v1/finance/fee-schedules",
        json={"program_id": str(uuid.uuid4()), "term_id": str(uuid.uuid4()), "amount_xaf": 450_000},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["amount_xaf"] == 450_000


async def test_student_cannot_create_fee_schedule(client) -> None:
    token = _mint_token(role="student")

    response = await client.post(
        "/api/v1/finance/fee-schedules",
        json={"program_id": str(uuid.uuid4()), "term_id": str(uuid.uuid4()), "amount_xaf": 450_000},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_duplicate_fee_schedule_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program_id = uuid.uuid4()
    term_id = uuid.uuid4()
    token = _mint_token(tenant_id=str(institution_id), role="admin")
    payload = {"program_id": str(program_id), "term_id": str(term_id), "amount_xaf": 450_000}

    first = await client.post(
        "/api/v1/finance/fee-schedules", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/finance/fee-schedules", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert second.status_code == 409


async def test_negative_fee_schedule_amount_is_rejected(client) -> None:
    token = _mint_token(role="admin")

    response = await client.post(
        "/api/v1/finance/fee-schedules",
        json={"program_id": str(uuid.uuid4()), "term_id": str(uuid.uuid4()), "amount_xaf": -1},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


async def test_fee_schedules_are_isolated_across_institutions(client) -> None:
    institution_a = uuid.uuid4()
    institution_b = uuid.uuid4()
    async with SessionFactory() as session:
        await set_platform_context(session)
        fee_schedule_a = FeeSchedule(
            institution_id=institution_a, program_id=uuid.uuid4(), term_id=uuid.uuid4(), amount_xaf=100_000
        )
        session.add(fee_schedule_a)
        await session.commit()

    token_b = _mint_token(tenant_id=str(institution_b), role="admin")
    response = await client.post(
        "/api/v1/finance/fee-schedules",
        json={"program_id": str(fee_schedule_a.program_id), "term_id": str(fee_schedule_a.term_id), "amount_xaf": 999},
        headers={"Authorization": f"Bearer {token_b}"},
    )

    # institution_b creating a fee schedule with the same program/term as
    # institution_a's must succeed - the uniqueness constraint is per
    # institution, proving the RLS-scoped uniqueness check isn't leaking
    # across tenants.
    assert response.status_code == 201
