"""Enrollment-creation tests. Require a real, migrated Postgres reachable via
DATABASE_URL (see readme.md) - these exercise real RLS and the transactional
outbox, not a mocked DB layer.
"""
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from jsonschema import validate
from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER
from app.core.tenant_context import set_platform_context
from app.main import app
from app.models.academic import OutboxEvent, Program, Term
from app.worker import _build_envelope

CONTRACTS_DIR = Path(__file__).parents[3] / "contracts" / "events"


def _private_key() -> str:
    path = os.environ["JWT_PRIVATE_KEY_PATH_FOR_TESTS"]
    return Path(path).read_text(encoding="utf-8")


def _mint_token(*, expires_delta: timedelta = timedelta(minutes=10), **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
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


async def _seed_program_and_term(institution_id: uuid.UUID) -> tuple[Program, Term]:
    unique = uuid.uuid4().hex[:10]
    async with SessionFactory() as session:
        await set_platform_context(session)
        program = Program(institution_id=institution_id, name=f"Test Program {unique}", code=f"P{unique}")
        term = Term(
            institution_id=institution_id,
            name=f"Term {unique}",
            starts_on=datetime.now(UTC),
            ends_on=datetime.now(UTC) + timedelta(days=90),
        )
        session.add_all([program, term])
        await session.commit()
        return program, term


async def _get_outbox_event(enrollment_id: uuid.UUID) -> OutboxEvent:
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(OutboxEvent).where(OutboxEvent.payload["enrollment_id"].astext == str(enrollment_id))
        )
        return result.scalar_one()


async def test_student_can_enroll_self(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    program, term = await _seed_program_and_term(institution_id)
    token = _mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/enrollments",
        json={"program_id": str(program.id), "term_id": str(term.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["student_id"] == str(student_id)
    assert body["program_id"] == str(program.id)
    assert body["term_id"] == str(term.id)
    assert body["status"] == "accepted"


async def test_enrollment_creates_exactly_one_outbox_event_matching_contract(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    program, term = await _seed_program_and_term(institution_id)
    token = _mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/enrollments",
        json={"program_id": str(program.id), "term_id": str(term.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    enrollment_id = uuid.UUID(response.json()["id"])

    event = await _get_outbox_event(enrollment_id)
    assert event.event_type == "academic.enrollment_accepted"
    assert event.schema_version == 1
    assert event.published_at is None

    envelope = _build_envelope(event)
    envelope_schema = json.loads((CONTRACTS_DIR / "envelope.schema.json").read_text(encoding="utf-8"))
    payload_schema = json.loads(
        (CONTRACTS_DIR / "enrollment-accepted.v1.schema.json").read_text(encoding="utf-8")
    )
    validate(instance=envelope, schema=envelope_schema)
    validate(instance=envelope["data"], schema=payload_schema)
    assert envelope["data"]["enrollment_id"] == str(enrollment_id)
    assert envelope["data"]["student_id"] == str(student_id)


async def test_staff_can_enroll_a_specific_student(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    program, term = await _seed_program_and_term(institution_id)
    token = _mint_token(sub=str(uuid.uuid4()), tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/enrollments",
        json={
            "program_id": str(program.id),
            "term_id": str(term.id),
            "student_id": str(student_id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["student_id"] == str(student_id)


async def test_staff_enrollment_without_student_id_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await _seed_program_and_term(institution_id)
    token = _mint_token(sub=str(uuid.uuid4()), tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/enrollments",
        json={"program_id": str(program.id), "term_id": str(term.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


async def test_student_cannot_enroll_another_student(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await _seed_program_and_term(institution_id)
    token = _mint_token(sub=str(uuid.uuid4()), tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/enrollments",
        json={
            "program_id": str(program.id),
            "term_id": str(term.id),
            "student_id": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_duplicate_enrollment_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    program, term = await _seed_program_and_term(institution_id)
    token = _mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    payload = {"program_id": str(program.id), "term_id": str(term.id)}

    first = await client.post(
        "/api/v1/academic/enrollments", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/academic/enrollments", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert second.status_code == 409


async def test_enrollment_in_unknown_program_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    _, term = await _seed_program_and_term(institution_id)
    token = _mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/enrollments",
        json={"program_id": str(uuid.uuid4()), "term_id": str(term.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_programs_are_isolated_across_institutions(client) -> None:
    institution_a = uuid.uuid4()
    institution_b = uuid.uuid4()
    program_a, _ = await _seed_program_and_term(institution_a)
    await _seed_program_and_term(institution_b)
    token_b = _mint_token(sub=str(uuid.uuid4()), tenant_id=str(institution_b), role="student")

    response = await client.get("/api/v1/academic/programs", headers={"Authorization": f"Bearer {token_b}"})

    assert response.status_code == 200
    program_ids = [row["id"] for row in response.json()]
    assert str(program_a.id) not in program_ids


async def test_student_only_sees_own_enrollments(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await _seed_program_and_term(institution_id)
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    token_a = _mint_token(sub=str(student_a), tenant_id=str(institution_id), role="student")
    token_b = _mint_token(sub=str(student_b), tenant_id=str(institution_id), role="student")
    payload = {"program_id": str(program.id), "term_id": str(term.id)}

    await client.post("/api/v1/academic/enrollments", json=payload, headers={"Authorization": f"Bearer {token_a}"})
    await client.post("/api/v1/academic/enrollments", json=payload, headers={"Authorization": f"Bearer {token_b}"})

    response = await client.get("/api/v1/academic/enrollments", headers={"Authorization": f"Bearer {token_a}"})

    assert response.status_code == 200
    student_ids = {row["student_id"] for row in response.json()}
    assert student_ids == {str(student_a)}
