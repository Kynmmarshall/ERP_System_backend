"""Idempotent dev-only seed data: the BSc Software Engineering programme and
two terms, each with its own six courses. NOT run automatically by
docker-compose or Jenkins - run manually:

    docker compose exec academic python -m scripts.seed <institution-id> [instructor-user-id]

Both ids come from identity's live data, NOT from a constant - the old
hardcoded institution id drifted from this workspace's volume and produced
courses no real user could see. Get them with:

    docker compose exec postgres psql -U identity_app -d identity_db -t -A \
      -c "SET app.is_platform_admin='true'; SELECT id, slug FROM institutions;"

Pass the lecturer's user id too, or the offerings get a placeholder
instructor and the lecturer dashboard will show nothing to grade.
"""
import asyncio
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.academic import Program, Term
from app.models.courses import Course, CourseOffering

SEN_PROGRAM_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
FALL_2026_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
SPRING_2027_ID = uuid.UUID("00000000-0000-4000-8000-000000000012")
# Placeholder used only when no instructor id is passed on the command line.
SEEDED_INSTRUCTOR_ID = uuid.UUID("00000000-0000-4000-8000-000000000030")

CREDITS_PER_COURSE = 6
COURSES_PER_SEMESTER = 6

# Each term carries its own six courses - a course belongs to the semester it
# is taught in, so the two catalogues never overlap. The short hex strings
# become fixed UUIDs so re-running the seed is a no-op.
TERMS = [
    (
        FALL_2026_ID,
        "Fall 2026",
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 12, 20, tzinfo=UTC),
        [
            ("20", "21", "CS101", "Introduction to Computer Science", "B12", 40),
            ("22", "23", "SEN310", "Large System Environment", "B14", 40),
            ("24", "25", "SEN320", "Mobile App Development", "Lab 1", 35),
            ("26", "27", "SEN330", "Software Project Management", "B16", 45),
            ("28", "29", "SEN340", "Ethical Hacking", "Lab 2", 30),
            ("2a", "2b", "SEN350", "Compiler Construction", "B18", 35),
        ],
    ),
    (
        SPRING_2027_ID,
        "Spring 2027",
        datetime(2027, 1, 11, tzinfo=UTC),
        datetime(2027, 5, 28, tzinfo=UTC),
        [
            ("2c", "2d", "SEN360", "Artificial Intelligence", "Lab 3", 35),
            ("2e", "2f", "SEN370", "Cloud and Distributed Systems", "B20", 40),
            ("30", "31", "SEN380", "Machine Learning", "Lab 3", 35),
            ("32", "33", "SEN390", "Web Services and APIs", "Lab 1", 35),
            ("34", "35", "SEN400", "Database Systems Administration", "B22", 40),
            ("36", "37", "SEN410", "Software Quality Assurance", "B24", 45),
        ],
    ),
]


def _fixed_id(suffix: str) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-4000-8000-0000000000{suffix}")


async def main(institution_id: uuid.UUID, instructor_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)

        existing_program = await session.execute(select(Program).where(Program.id == SEN_PROGRAM_ID))
        if existing_program.scalar_one_or_none() is None:
            session.add(
                Program(
                    id=SEN_PROGRAM_ID,
                    institution_id=institution_id,
                    name="BSc Software Engineering",
                    code="SEN",
                )
            )
            print(f"Created program {SEN_PROGRAM_ID} (SEN)")

        for term_id, term_name, starts_on, ends_on, courses in TERMS:
            existing_term = await session.execute(select(Term).where(Term.id == term_id))
            term = existing_term.scalar_one_or_none()
            if term is None:
                session.add(
                    Term(
                        id=term_id,
                        institution_id=institution_id,
                        name=term_name,
                        starts_on=starts_on,
                        ends_on=ends_on,
                    )
                )
                print(f"Created term {term_name}")
            elif term.name != term_name:
                print(f"Renamed term {term.name} -> {term_name}")
                term.name = term_name

            print(f"{term_name}:")
            for course_suffix, offering_suffix, code, name, room, capacity in courses:
                # Matched on code within this institution, not on id: a course
                # created through the UI has a random id, and matching on id
                # alone would seed a duplicate of it.
                existing_course = await session.execute(
                    select(Course).where(
                        Course.institution_id == institution_id, Course.code == code
                    )
                )
                course = existing_course.scalars().first()
                if course is None:
                    course = Course(
                        id=_fixed_id(course_suffix),
                        institution_id=institution_id,
                        program_id=SEN_PROGRAM_ID,
                        code=code,
                        name=name,
                        credits=CREDITS_PER_COURSE,
                    )
                    session.add(course)
                    await session.flush()
                    print(f"  created {code} - {name}")
                elif course.credits != CREDITS_PER_COURSE:
                    course.credits = CREDITS_PER_COURSE
                    print(f"  {code} updated to {CREDITS_PER_COURSE} credits")

                existing_offering = await session.execute(
                    select(CourseOffering).where(
                        CourseOffering.course_id == course.id,
                        CourseOffering.term_id == term_id,
                    )
                )
                offering = existing_offering.scalars().first()
                if offering is None:
                    session.add(
                        CourseOffering(
                            id=_fixed_id(offering_suffix),
                            institution_id=institution_id,
                            course_id=course.id,
                            term_id=term_id,
                            instructor_id=instructor_id,
                            room=room,
                            capacity=capacity,
                        )
                    )
                    print(f"  {code} offered in {room} (capacity {capacity})")
                elif offering.instructor_id != instructor_id:
                    offering.instructor_id = instructor_id
                    print(f"  {code} offering reassigned to instructor {instructor_id}")

        await session.commit()

    load = COURSES_PER_SEMESTER * CREDITS_PER_COURSE
    print(f"\nEach semester: {COURSES_PER_SEMESTER} courses x {CREDITS_PER_COURSE} credits = {load}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: python -m scripts.seed <institution-id> [instructor-user-id]\n"
            "Get the institution id from identity - never assume it."
        )
    tenant = uuid.UUID(sys.argv[1])
    supplied = uuid.UUID(sys.argv[2]) if len(sys.argv) > 2 else SEEDED_INSTRUCTOR_ID
    asyncio.run(main(tenant, supplied))
