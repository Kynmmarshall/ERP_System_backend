import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_claims, get_tenant_session, require_roles
from app.models.academic import Enrollment, Program, Term
from app.models.courses import Course, CourseOffering, CoursePrerequisite, CourseRegistration
from app.schemas import (
    CourseCreateRequest,
    CourseOfferingCreateRequest,
    CourseOfferingResponse,
    CourseRegistrationCreateRequest,
    CourseRegistrationResponse,
    CourseResponse,
    PrerequisiteCreateRequest,
    PrerequisiteResponse,
)

router = APIRouter()

_STAFF_ROLES = ("admin", "staff", "super_admin")


@router.post(
    "/courses",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_STAFF_ROLES))],
)
async def create_course(
    payload: CourseCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> Course:
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")

    program = await session.get(Program, payload.program_id)
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")

    course = Course(
        institution_id=uuid.UUID(tenant_id),
        program_id=payload.program_id,
        code=payload.code,
        name=payload.name,
        credits=payload.credits,
    )
    session.add(course)
    await session.commit()
    return course


@router.get("/courses", response_model=list[CourseResponse])
async def list_courses(
    program_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Course]:
    query = select(Course).order_by(Course.code)
    if program_id is not None:
        query = query.where(Course.program_id == program_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def _would_create_cycle(
    session: AsyncSession, *, institution_id: uuid.UUID, course_id: uuid.UUID, prerequisite_course_id: uuid.UUID
) -> bool:
    """course_id -> prerequisite_course_id is the edge being added (course_id
    requires prerequisite_course_id). It closes a cycle if course_id is
    already reachable by walking forward from prerequisite_course_id.
    """
    if course_id == prerequisite_course_id:
        return True
    result = await session.execute(
        text(
            """
            WITH RECURSIVE reach(node) AS (
                SELECT prerequisite_course_id FROM course_prerequisites
                WHERE institution_id = :institution_id AND course_id = :start
                UNION
                SELECT cp.prerequisite_course_id FROM course_prerequisites cp
                JOIN reach r ON cp.course_id = r.node
                WHERE cp.institution_id = :institution_id
            )
            SELECT 1 FROM reach WHERE node = :target LIMIT 1
            """
        ),
        {"institution_id": str(institution_id), "start": str(prerequisite_course_id), "target": str(course_id)},
    )
    return result.first() is not None


@router.post(
    "/courses/{course_id}/prerequisites",
    response_model=PrerequisiteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_STAFF_ROLES))],
)
async def add_prerequisite(
    course_id: uuid.UUID,
    payload: PrerequisiteCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> CoursePrerequisite:
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")
    institution_id = uuid.UUID(tenant_id)

    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    prerequisite = await session.get(Course, payload.prerequisite_course_id)
    if prerequisite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prerequisite course not found")

    if await _would_create_cycle(
        session,
        institution_id=institution_id,
        course_id=course_id,
        prerequisite_course_id=payload.prerequisite_course_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This prerequisite would create a cycle"
        )

    edge = CoursePrerequisite(
        institution_id=institution_id, course_id=course_id, prerequisite_course_id=payload.prerequisite_course_id
    )
    session.add(edge)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prerequisite already exists") from exc
    return edge


@router.get("/courses/{course_id}/prerequisites", response_model=list[PrerequisiteResponse])
async def list_prerequisites(
    course_id: uuid.UUID, session: AsyncSession = Depends(get_tenant_session)
) -> list[CoursePrerequisite]:
    result = await session.execute(select(CoursePrerequisite).where(CoursePrerequisite.course_id == course_id))
    return list(result.scalars().all())


@router.post(
    "/course-offerings",
    response_model=CourseOfferingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_STAFF_ROLES))],
)
async def create_course_offering(
    payload: CourseOfferingCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> CourseOffering:
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")

    course = await session.get(Course, payload.course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    term = await session.get(Term, payload.term_id)
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")

    offering = CourseOffering(
        institution_id=uuid.UUID(tenant_id),
        course_id=payload.course_id,
        term_id=payload.term_id,
        instructor_id=payload.instructor_id,
        room=payload.room,
        capacity=payload.capacity,
    )
    session.add(offering)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This course already has an offering for that term"
        ) from exc
    return offering


@router.get("/course-offerings", response_model=list[CourseOfferingResponse])
async def list_course_offerings(
    term_id: uuid.UUID | None = Query(default=None),
    course_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[CourseOffering]:
    query = select(CourseOffering)
    if term_id is not None:
        query = query.where(CourseOffering.term_id == term_id)
    if course_id is not None:
        query = query.where(CourseOffering.course_id == course_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def _unmet_prerequisites(
    session: AsyncSession, *, student_id: uuid.UUID, course_id: uuid.UUID
) -> list[uuid.UUID]:
    """Returns the prerequisite course ids the student has NOT passed yet
    (no published course average >=50 in any offering of that course)."""
    prereq_result = await session.execute(
        select(CoursePrerequisite.prerequisite_course_id).where(CoursePrerequisite.course_id == course_id)
    )
    prerequisite_ids = [row[0] for row in prereq_result.all()]
    if not prerequisite_ids:
        return []

    unmet: list[uuid.UUID] = []
    for prerequisite_id in prerequisite_ids:
        passed = await session.execute(
            text(
                """
                SELECT 1
                FROM course_offerings co
                JOIN assessments a ON a.course_offering_id = co.id
                JOIN grades g ON g.assessment_id = a.id
                WHERE co.course_id = :course_id
                  AND g.student_id = :student_id
                  AND g.published = true
                GROUP BY co.id
                HAVING AVG(g.score / a.max_score * 100) >= 50
                LIMIT 1
                """
            ),
            {"course_id": str(prerequisite_id), "student_id": str(student_id)},
        )
        if passed.first() is None:
            unmet.append(prerequisite_id)
    return unmet


@router.post(
    "/course-registrations", response_model=CourseRegistrationResponse, status_code=status.HTTP_201_CREATED
)
async def create_course_registration(
    payload: CourseRegistrationCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> CourseRegistration:
    if claims.get("role") != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students register for courses")
    student_id = uuid.UUID(claims["sub"])
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")

    enrollment = await session.get(Enrollment, payload.enrollment_id)
    if enrollment is None or enrollment.student_id != student_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found")

    offering = await session.get(CourseOffering, payload.course_offering_id)
    if offering is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course offering not found")
    if offering.term_id != enrollment.term_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Course offering is not in the enrolled term"
        )

    course = await session.get(Course, offering.course_id)
    if course is not None and course.program_id != enrollment.program_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Course does not belong to the enrolled program"
        )

    unmet = await _unmet_prerequisites(session, student_id=student_id, course_id=offering.course_id)
    if unmet:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Unmet prerequisites", "missing_course_ids": [str(cid) for cid in unmet]},
        )

    existing = await session.execute(
        select(CourseRegistration).where(
            CourseRegistration.student_id == student_id,
            CourseRegistration.course_offering_id == offering.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already registered")

    registration = CourseRegistration(
        institution_id=uuid.UUID(tenant_id),
        student_id=student_id,
        enrollment_id=enrollment.id,
        course_offering_id=offering.id,
    )
    session.add(registration)
    await session.commit()
    return registration


@router.get("/course-registrations", response_model=list[CourseRegistrationResponse])
async def list_course_registrations(
    course_offering_id: uuid.UUID | None = Query(default=None),
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[CourseRegistration]:
    query = select(CourseRegistration)
    if claims.get("role") == "student":
        query = query.where(CourseRegistration.student_id == uuid.UUID(claims["sub"]))
    if course_offering_id is not None:
        query = query.where(CourseRegistration.course_offering_id == course_offering_id)
    result = await session.execute(query)
    return list(result.scalars().all())
