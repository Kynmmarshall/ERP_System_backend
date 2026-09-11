"""Shared test helpers for Phase 6 hr tests - see finance's tests/helpers.py
for the same pattern."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import jwt

from app.core.db import SessionFactory
from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER
from app.core.tenant_context import set_platform_context
from app.models.employees import Employee, EmployeeStatus
from app.models.payroll import PayrollScheduleVersion
from app.models.recruitment import Candidate, CandidateStage, Position, PositionStatus


def private_key() -> str:
    path = os.environ["JWT_PRIVATE_KEY_PATH_FOR_TESTS"]
    return Path(path).read_text(encoding="utf-8")


def mint_token(*, expires_delta: timedelta = timedelta(minutes=10), **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "campus_id": None,
        "role": "staff",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key(), algorithm=JWT_ALGORITHM)


async def seed_employee(
    institution_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    full_name: str = "Jane Employee",
    email: str = "jane.employee@example.com",
    department: str = "Registry",
    hire_date: date = date(2024, 1, 15),
    gross_monthly_salary_xaf: int = 500_000,
    status: EmployeeStatus = EmployeeStatus.ACTIVE,
) -> Employee:
    async with SessionFactory() as session:
        await set_platform_context(session)
        employee = Employee(
            institution_id=institution_id,
            user_id=user_id,
            full_name=full_name,
            email=email,
            department=department,
            hire_date=hire_date,
            gross_monthly_salary_xaf=gross_monthly_salary_xaf,
            status=status,
        )
        session.add(employee)
        await session.commit()
        return employee


async def seed_position(
    institution_id: uuid.UUID, *, title: str = "Registrar", department: str = "Registry"
) -> Position:
    async with SessionFactory() as session:
        await set_platform_context(session)
        position = Position(
            institution_id=institution_id, title=title, department=department, status=PositionStatus.OPEN
        )
        session.add(position)
        await session.commit()
        return position


async def seed_candidate(
    institution_id: uuid.UUID,
    position_id: uuid.UUID,
    *,
    full_name: str = "Candid Ate",
    email: str = "candid.ate@example.com",
    stage: CandidateStage = CandidateStage.APPLIED,
) -> Candidate:
    async with SessionFactory() as session:
        await set_platform_context(session)
        candidate = Candidate(
            institution_id=institution_id,
            position_id=position_id,
            full_name=full_name,
            email=email,
            stage=stage,
        )
        session.add(candidate)
        await session.commit()
        return candidate


# Example/illustrative rate schedule only - matches the seeded baseline
# schedule's is_verified=false intent (see phase6-plan.md). Never treat
# these numbers as real CNPS/DGI rates.
EXAMPLE_IRPP_BRACKETS = [
    {"up_to_xaf": 200_000, "rate": 0.10},
    {"up_to_xaf": 300_000, "rate": 0.15},
    {"up_to_xaf": 500_000, "rate": 0.25},
    {"up_to_xaf": None, "rate": 0.35},
]


async def seed_schedule_version(
    institution_id: uuid.UUID,
    *,
    is_verified: bool = False,
    effective_from: date = date(2024, 1, 1),
    cnps_employee_rate: Decimal = Decimal("0.042"),
    cnps_employer_rate: Decimal = Decimal("0.070"),
    cnps_ceiling_xaf: int = 750_000,
    standard_deduction_rate: Decimal = Decimal("0.30"),
    irpp_brackets: list[dict] | None = None,
) -> PayrollScheduleVersion:
    async with SessionFactory() as session:
        await set_platform_context(session)
        schedule = PayrollScheduleVersion(
            institution_id=institution_id,
            effective_from=effective_from,
            is_verified=is_verified,
            cnps_employee_rate=cnps_employee_rate,
            cnps_employer_rate=cnps_employer_rate,
            cnps_ceiling_xaf=cnps_ceiling_xaf,
            standard_deduction_rate=standard_deduction_rate,
            irpp_brackets=irpp_brackets if irpp_brackets is not None else EXAMPLE_IRPP_BRACKETS,
        )
        session.add(schedule)
        await session.commit()
        return schedule
