import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_qr_token, issue_qr_token
from app.deps import get_tenant_session, require_roles
from app.models.attendance import AttendanceRecord, AttendanceShift
from app.models.employees import Employee
from app.schemas import (
    AttendanceRecordResponse,
    CheckInRequest,
    QRTokenResponse,
    ShiftCreateRequest,
    ShiftResponse,
)

router = APIRouter()

_HR_ADMIN_ROLES = ("admin", "super_admin")
_STAFF_ROLES = ("admin", "staff", "lecturer", "finance_staff", "super_admin")

QR_TOKEN_VALIDITY = timedelta(minutes=10)


async def _get_own_employee(session: AsyncSession, claims: dict) -> Employee:
    result = await session.execute(select(Employee).where(Employee.user_id == uuid.UUID(claims["sub"])))
    employee = result.scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account")
    return employee


@router.post("/attendance/shifts", response_model=ShiftResponse, status_code=status.HTTP_201_CREATED)
async def create_shift(
    payload: ShiftCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> AttendanceShift:
    employee = await session.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    shift = AttendanceShift(
        institution_id=uuid.UUID(claims["tenant_id"]),
        employee_id=payload.employee_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    session.add(shift)
    await session.commit()
    return shift


@router.get("/attendance/shifts", response_model=list[ShiftResponse])
async def list_shifts(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AttendanceShift]:
    result = await session.execute(select(AttendanceShift).order_by(AttendanceShift.starts_at.desc()))
    return list(result.scalars().all())


@router.post("/attendance/shifts/{shift_id}/qr-token", response_model=QRTokenResponse)
async def issue_shift_qr_token(
    shift_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> QRTokenResponse:
    """Issuing a new token overwrites the shift's stored jti, so any
    previously issued QR code for this shift is immediately invalidated
    even if it has not yet expired.
    """
    shift = await session.get(AttendanceShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")

    jti = uuid.uuid4()
    expires_at = datetime.now(UTC) + QR_TOKEN_VALIDITY
    token = issue_qr_token(shift_id=shift.id, jti=jti, expires_delta=QR_TOKEN_VALIDITY)
    shift.qr_token_jti = jti
    await session.commit()
    return QRTokenResponse(token=token, expires_at=expires_at)


@router.post("/attendance/check-in", response_model=AttendanceRecordResponse, status_code=status.HTTP_201_CREATED)
async def check_in(
    payload: CheckInRequest,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> AttendanceRecord:
    try:
        token_claims = decode_qr_token(payload.token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired QR token") from exc

    shift = await session.get(AttendanceShift, uuid.UUID(token_claims["shift_id"]))
    if shift is None or str(shift.qr_token_jti) != token_claims["jti"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="QR token no longer valid for this shift")

    employee = await _get_own_employee(session, claims)
    if shift.employee_id != employee.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This shift does not belong to you")

    record = AttendanceRecord(institution_id=shift.institution_id, shift_id=shift.id, employee_id=employee.id)
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already checked in for this shift") from exc
    return record


@router.get("/attendance/mine", response_model=list[AttendanceRecordResponse])
async def list_my_attendance(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AttendanceRecord]:
    employee = await _get_own_employee(session, claims)
    result = await session.execute(
        select(AttendanceRecord)
        .where(AttendanceRecord.employee_id == employee.id)
        .order_by(AttendanceRecord.checked_in_at.desc())
    )
    return list(result.scalars().all())
