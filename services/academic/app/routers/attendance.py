import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import ensure_can_manage_offering
from app.deps import get_current_claims, get_tenant_session
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.courses import CourseOffering
from app.schemas import (
    AttendanceMarkRequest,
    AttendanceRecordResponse,
    AttendanceSessionCreateRequest,
    AttendanceSessionResponse,
)

router = APIRouter()


async def _get_offering_or_404(session: AsyncSession, course_offering_id: uuid.UUID) -> CourseOffering:
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course offering not found")
    return offering


@router.post(
    "/attendance-sessions", response_model=AttendanceSessionResponse, status_code=status.HTTP_201_CREATED
)
async def create_attendance_session(
    payload: AttendanceSessionCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> AttendanceSession:
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")

    offering = await _get_offering_or_404(session, payload.course_offering_id)
    ensure_can_manage_offering(offering, claims)

    attendance_session = AttendanceSession(
        institution_id=uuid.UUID(tenant_id),
        course_offering_id=payload.course_offering_id,
        session_date=payload.session_date,
    )
    session.add(attendance_session)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A session already exists for that date"
        ) from exc
    return attendance_session


@router.post("/attendance-sessions/{session_id}/records", response_model=list[AttendanceRecordResponse])
async def mark_attendance(
    session_id: uuid.UUID,
    payload: AttendanceMarkRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AttendanceRecord]:
    attendance_session = await session.get(AttendanceSession, session_id)
    if attendance_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance session not found")
    offering = await _get_offering_or_404(session, attendance_session.course_offering_id)
    ensure_can_manage_offering(offering, claims)

    records = []
    for entry in payload.records:
        existing = await session.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.attendance_session_id == session_id,
                AttendanceRecord.student_id == entry.student_id,
            )
        )
        record = existing.scalar_one_or_none()
        if record is None:
            record = AttendanceRecord(
                institution_id=attendance_session.institution_id,
                attendance_session_id=session_id,
                student_id=entry.student_id,
                present=entry.present,
            )
            session.add(record)
        else:
            record.present = entry.present
        records.append(record)

    await session.commit()
    return records


@router.get("/attendance-sessions/{session_id}/records", response_model=list[AttendanceRecordResponse])
async def list_attendance_records(
    session_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AttendanceRecord]:
    query = select(AttendanceRecord).where(AttendanceRecord.attendance_session_id == session_id)
    if claims.get("role") == "student":
        query = query.where(AttendanceRecord.student_id == uuid.UUID(claims["sub"]))
    result = await session.execute(query)
    return list(result.scalars().all())


@router.get("/attendance-sessions", response_model=list[AttendanceSessionResponse])
async def list_attendance_sessions(
    course_offering_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AttendanceSession]:
    result = await session.execute(
        select(AttendanceSession)
        .where(AttendanceSession.course_offering_id == course_offering_id)
        .order_by(AttendanceSession.session_date)
    )
    return list(result.scalars().all())
