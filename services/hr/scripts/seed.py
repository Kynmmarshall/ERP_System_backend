"""Idempotent-ish dev-only seed data: one Employee linked to the seeded
staff@ictuniversity.example identity user (so the frontend's self-service
People page has real data to show), plus an example (deliberately
unverified) payroll schedule version. NOT run automatically by
docker-compose or Jenkins - run manually, after capturing the staff
account's real user id (its "sub" claim - identity assigns User.id
randomly, it is not a fixed constant like the institution id):

    docker compose exec hr python -m scripts.seed <staff-user-id>

IDs must match services/identity/scripts/seed.py (duplicated literal
constants, not shared code).
"""
import asyncio
import sys
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.employees import Employee
from app.models.payroll import PayrollScheduleVersion

ICT_MAIN_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

# Illustrative/example only - never real CNPS/DGI rates. Deliberately
# is_verified=false; see phase6-plan.md for why this is the release gate.
EXAMPLE_IRPP_BRACKETS = [
    {"up_to_xaf": 200_000, "rate": 0.10},
    {"up_to_xaf": 300_000, "rate": 0.15},
    {"up_to_xaf": 500_000, "rate": 0.25},
    {"up_to_xaf": None, "rate": 0.35},
]


async def main(staff_user_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)

        existing_employee = await session.execute(select(Employee).where(Employee.user_id == staff_user_id))
        employee = existing_employee.scalar_one_or_none()
        if employee is None:
            employee = Employee(
                institution_id=ICT_MAIN_INSTITUTION_ID,
                user_id=staff_user_id,
                full_name="ICT University Staff",
                email="staff@ictuniversity.example",
                department="Registry",
                hire_date=date(2024, 1, 15),
                gross_monthly_salary_xaf=500_000,
            )
            session.add(employee)
            print(f"Created employee for user {staff_user_id}")
        else:
            print(f"Employee already exists for user {staff_user_id}")

        existing_schedule = await session.execute(
            select(PayrollScheduleVersion).where(
                PayrollScheduleVersion.institution_id == ICT_MAIN_INSTITUTION_ID,
                PayrollScheduleVersion.effective_from == date(2024, 1, 1),
            )
        )
        if existing_schedule.scalar_one_or_none() is None:
            session.add(
                PayrollScheduleVersion(
                    institution_id=ICT_MAIN_INSTITUTION_ID,
                    effective_from=date(2024, 1, 1),
                    is_verified=False,
                    cnps_employee_rate=Decimal("0.042"),
                    cnps_employer_rate=Decimal("0.070"),
                    cnps_ceiling_xaf=750_000,
                    standard_deduction_rate=Decimal("0.30"),
                    irpp_brackets=EXAMPLE_IRPP_BRACKETS,
                )
            )
            print("Created example (unverified) payroll schedule version")

        await session.commit()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.seed <staff-user-id>")
    asyncio.run(main(uuid.UUID(sys.argv[1])))
