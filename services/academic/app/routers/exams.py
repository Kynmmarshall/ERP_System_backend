import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import ensure_can_manage_offering
from app.deps import get_current_claims, get_tenant_session
from app.models.courses import CourseOffering
from app.models.exams import ExamSchedule
from app.schemas import ExamScheduleCreateRequest, ExamScheduleResponse

router = APIRouter()


async def _lock_term_schedule(session: AsyncSession, *, institution_id: uuid.UUID, term_id: uuid.UUID) -> None:
    """Serializes concurrent exam-scheduling attempts for the same
    institution+term so two overlapping requests cannot both pass the
    conflict checks below before either commits.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"),
        {"key": f"{institution_id}:{term_id}"},
    )


_NIL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _find_conflict(
    session: AsyncSession,
    *,
    term_id: uuid.UUID,
    course_offering_id: uuid.UUID,
    instructor_id: uuid.UUID,
    room: str,
    starts_at: datetime,
    ends_at: datetime,
    exclude_id: uuid.UUID | None,
) -> str | None:
    # exclude_id defaults to a UUID no real row can ever have, instead of
    # conditionally interpolating the exclusion clause into the SQL text.
    params = {
        "term_id": str(term_id),
        "room": room,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "exclude_id": str(exclude_id or _NIL_UUID),
    }

    room_conflict = await session.execute(
        text(
            """
            SELECT 1 FROM exam_schedules es
            WHERE es.term_id = :term_id AND es.room = :room AND es.id != :exclude_id
              AND es.starts_at < :ends_at AND es.ends_at > :starts_at
            LIMIT 1
            """
        ),
        params,
    )
    if room_conflict.first() is not None:
        return "room"

    instructor_conflict = await session.execute(
        text(
            """
            SELECT 1 FROM exam_schedules es
            JOIN course_offerings co ON co.id = es.course_offering_id
            WHERE es.term_id = :term_id AND co.instructor_id = :instructor_id AND es.id != :exclude_id
              AND es.starts_at < :ends_at AND es.ends_at > :starts_at
            LIMIT 1
            """
        ),
        {**params, "instructor_id": str(instructor_id)},
    )
    if instructor_conflict.first() is not None:
        return "instructor"

    student_conflict = await session.execute(
        text(
            """
            SELECT 1 FROM exam_schedules es
            JOIN course_registrations cr ON cr.course_offering_id = es.course_offering_id
            WHERE es.term_id = :term_id AND es.id != :exclude_id
              AND es.starts_at < :ends_at AND es.ends_at > :starts_at
              AND cr.student_id IN (
                  SELECT student_id FROM course_registrations WHERE course_offering_id = :offering_id
              )
            LIMIT 1
            """
        ),
        {**params, "offering_id": str(course_offering_id)},
    )
    if student_conflict.first() is not None:
        return "student"

    return None


@router.post("/exam-schedules", response_model=ExamScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_exam_schedule(
    payload: ExamScheduleCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> ExamSchedule:
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")
    institution_id = uuid.UUID(tenant_id)

    offering = await session.get(CourseOffering, payload.course_offering_id)
    if offering is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course offering not found")
    ensure_can_manage_offering(offering, claims)

    if payload.starts_at >= payload.ends_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="starts_at must be before ends_at")

    await _lock_term_schedule(session, institution_id=institution_id, term_id=offering.term_id)

    conflict = await _find_conflict(
        session,
        term_id=offering.term_id,
        course_offering_id=offering.id,
        instructor_id=offering.instructor_id,
        room=payload.room,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        exclude_id=None,
    )
    if conflict is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{conflict} conflict at that time")

    exam_schedule = ExamSchedule(
        institution_id=institution_id,
        term_id=offering.term_id,
        course_offering_id=offering.id,
        room=payload.room,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    session.add(exam_schedule)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This course offering already has an exam scheduled"
        ) from exc
    return exam_schedule


@router.put("/exam-schedules/{exam_schedule_id}", response_model=ExamScheduleResponse)
async def reschedule_exam(
    exam_schedule_id: uuid.UUID,
    payload: ExamScheduleCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> ExamSchedule:
    exam_schedule = await session.get(ExamSchedule, exam_schedule_id)
    if exam_schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam schedule not found")
    offering = await session.get(CourseOffering, exam_schedule.course_offering_id)
    if offering is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course offering not found")
    ensure_can_manage_offering(offering, claims)

    if payload.starts_at >= payload.ends_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="starts_at must be before ends_at")

    await _lock_term_schedule(session, institution_id=offering.institution_id, term_id=offering.term_id)

    conflict = await _find_conflict(
        session,
        term_id=offering.term_id,
        course_offering_id=offering.id,
        instructor_id=offering.instructor_id,
        room=payload.room,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        exclude_id=exam_schedule.id,
    )
    if conflict is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{conflict} conflict at that time")

    exam_schedule.room = payload.room
    exam_schedule.starts_at = payload.starts_at
    exam_schedule.ends_at = payload.ends_at
    await session.commit()
    return exam_schedule


@router.get("/exam-schedules", response_model=list[ExamScheduleResponse])
async def list_exam_schedules(
    term_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[ExamSchedule]:
    result = await session.execute(
        select(ExamSchedule).where(ExamSchedule.term_id == term_id).order_by(ExamSchedule.starts_at)
    )
    return list(result.scalars().all())
