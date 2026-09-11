"""Idempotent dev-only seed data: one Program, Term, Course and
CourseOffering for ICT University. NOT run automatically by docker-compose
or Jenkins - run manually:

    docker compose exec academic python -m scripts.seed

Institution ID must match services/identity/scripts/seed.py's
ICT_MAIN_INSTITUTION_ID (duplicated literal constant, not shared code).
"""
import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.academic import Program, Term
from app.models.courses import Course, CourseOffering

ICT_MAIN_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SEN_PROGRAM_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
TERM_2026_S1_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
INTRO_CS_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000020")
INTRO_CS_OFFERING_ID = uuid.UUID("00000000-0000-4000-8000-000000000021")
# Matches identity's seeded staff@ictuniversity.example dev account - see
# services/identity/scripts/seed.py (staff has no fixed id there, so this
# is only a stable placeholder; real deployments assign instructor_id from
# an actual identity user id at course-offering creation time).
SEEDED_INSTRUCTOR_ID = uuid.UUID("00000000-0000-4000-8000-000000000030")


async def main() -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)

        existing_program = await session.execute(select(Program).where(Program.id == SEN_PROGRAM_ID))
        if existing_program.scalar_one_or_none() is None:
            session.add(
                Program(
                    id=SEN_PROGRAM_ID,
                    institution_id=ICT_MAIN_INSTITUTION_ID,
                    name="BSc Software Engineering",
                    code="SEN",
                )
            )
            print(f"Created program {SEN_PROGRAM_ID} (SEN)")

        existing_term = await session.execute(select(Term).where(Term.id == TERM_2026_S1_ID))
        if existing_term.scalar_one_or_none() is None:
            session.add(
                Term(
                    id=TERM_2026_S1_ID,
                    institution_id=ICT_MAIN_INSTITUTION_ID,
                    name="2026 Semester 1",
                    starts_on=datetime(2026, 9, 1, tzinfo=UTC),
                    ends_on=datetime(2026, 12, 20, tzinfo=UTC),
                )
            )
            print(f"Created term {TERM_2026_S1_ID} (2026 Semester 1)")

        existing_course = await session.execute(select(Course).where(Course.id == INTRO_CS_COURSE_ID))
        if existing_course.scalar_one_or_none() is None:
            session.add(
                Course(
                    id=INTRO_CS_COURSE_ID,
                    institution_id=ICT_MAIN_INSTITUTION_ID,
                    program_id=SEN_PROGRAM_ID,
                    code="CS101",
                    name="Introduction to Computer Science",
                    credits=4,
                )
            )
            print(f"Created course {INTRO_CS_COURSE_ID} (CS101)")

        existing_offering = await session.execute(
            select(CourseOffering).where(CourseOffering.id == INTRO_CS_OFFERING_ID)
        )
        if existing_offering.scalar_one_or_none() is None:
            session.add(
                CourseOffering(
                    id=INTRO_CS_OFFERING_ID,
                    institution_id=ICT_MAIN_INSTITUTION_ID,
                    course_id=INTRO_CS_COURSE_ID,
                    term_id=TERM_2026_S1_ID,
                    instructor_id=SEEDED_INSTRUCTOR_ID,
                    room="B12",
                    capacity=40,
                )
            )
            print(f"Created course offering {INTRO_CS_OFFERING_ID} (CS101 / 2026 Semester 1)")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())

