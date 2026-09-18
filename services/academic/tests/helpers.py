"""Shared test helpers for Phase 3+4 academic tests. Not a conftest fixture
module - these are plain functions imported directly, since fixtures would
force a specific institution/course graph shape on every test that doesn't
need it.
"""
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

from app.core.db import SessionFactory
from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER
from app.core.tenant_context import set_platform_context
from app.models.academic import Enrollment, Program, Term
from app.models.courses import Course, CourseOffering


def private_key() -> str:
    path = os.environ["JWT_PRIVATE_KEY_PATH_FOR_TESTS"]
    return Path(path).read_text(encoding="utf-8")


def mint_token(*, expires_delta: timedelta = timedelta(minutes=10), **overrides) -> str:
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
    return jwt.encode(claims, private_key(), algorithm=JWT_ALGORITHM)


async def seed_program_and_term(institution_id: uuid.UUID) -> tuple[Program, Term]:
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


async def seed_course(institution_id: uuid.UUID, program_id: uuid.UUID, *, code: str | None = None) -> Course:
    unique = code or f"C{uuid.uuid4().hex[:8]}"
    async with SessionFactory() as session:
        await set_platform_context(session)
        course = Course(institution_id=institution_id, program_id=program_id, code=unique, name=f"Course {unique}")
        session.add(course)
        await session.commit()
        return course


async def seed_course_offering(
    institution_id: uuid.UUID,
    course_id: uuid.UUID,
    term_id: uuid.UUID,
    *,
    instructor_id: uuid.UUID,
    room: str = "Room 1",
) -> CourseOffering:
    async with SessionFactory() as session:
        await set_platform_context(session)
        offering = CourseOffering(
            institution_id=institution_id,
            course_id=course_id,
            term_id=term_id,
            instructor_id=instructor_id,
            room=room,
        )
        session.add(offering)
        await session.commit()
        return offering


async def seed_enrollment(
    institution_id: uuid.UUID,
    student_id: uuid.UUID,
    program_id: uuid.UUID,
    term_id: uuid.UUID,
) -> Enrollment:
    async with SessionFactory() as session:
        await set_platform_context(session)
        enrollment = Enrollment(
            institution_id=institution_id,
            student_id=student_id,
            program_id=program_id,
            term_id=term_id,
        )
        session.add(enrollment)
        await session.commit()
        return enrollment
