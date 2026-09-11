import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.models.employees import Employee
from app.models.leave import LeaveRequest, LeaveStatus, Notification
from app.schemas import (
    LeaveDecisionRequest,
    LeaveRequestCreateRequest,
    LeaveRequestResponse,
    NotificationResponse,
)

router = APIRouter()

_HR_ADMIN_ROLES = ("admin", "super_admin")
_STAFF_ROLES = ("admin", "staff", "super_admin")


async def _get_own_employee(session: AsyncSession, claims: dict) -> Employee:
    result = await session.execute(select(Employee).where(Employee.user_id == uuid.UUID(claims["sub"])))
    employee = result.scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account")
    return employee


@router.post("/leave/requests", response_model=LeaveRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_leave_request(
    payload: LeaveRequestCreateRequest,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> LeaveRequest:
    employee = await _get_own_employee(session, claims)
    if payload.ends_on < payload.starts_on:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ends_on before starts_on")

    leave_request = LeaveRequest(
        institution_id=uuid.UUID(claims["tenant_id"]),
        employee_id=employee.id,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        reason=payload.reason,
        status=LeaveStatus.PENDING,
    )
    session.add(leave_request)
    await session.commit()
    return leave_request


@router.get("/leave/requests/mine", response_model=list[LeaveRequestResponse])
async def list_my_leave_requests(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[LeaveRequest]:
    employee = await _get_own_employee(session, claims)
    result = await session.execute(
        select(LeaveRequest).where(LeaveRequest.employee_id == employee.id).order_by(LeaveRequest.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/leave/requests", response_model=list[LeaveRequestResponse])
async def list_leave_requests(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[LeaveRequest]:
    result = await session.execute(select(LeaveRequest).order_by(LeaveRequest.created_at.desc()))
    return list(result.scalars().all())


@router.post("/leave/requests/{request_id}/decision", response_model=LeaveRequestResponse)
async def decide_leave_request(
    request_id: uuid.UUID,
    payload: LeaveDecisionRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> LeaveRequest:
    leave_request = await session.get(LeaveRequest, request_id)
    if leave_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave request not found")
    if leave_request.status != LeaveStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Leave request already decided")

    employee = await session.get(Employee, leave_request.employee_id)
    decider_user_id = uuid.UUID(claims["sub"])
    if employee is not None and employee.user_id == decider_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot decide your own leave request")

    leave_request.status = LeaveStatus.APPROVED if payload.approve else LeaveStatus.REJECTED
    leave_request.decided_by = decider_user_id
    leave_request.decided_at = datetime.now(UTC)

    if employee is not None and employee.user_id is not None:
        verb = "approved" if payload.approve else "rejected"
        session.add(
            Notification(
                institution_id=leave_request.institution_id,
                user_id=employee.user_id,
                message=f"Your leave request for {leave_request.starts_on} to {leave_request.ends_on} was {verb}.",
            )
        )

    await session.commit()
    return leave_request


@router.get("/notifications/mine", response_model=list[NotificationResponse])
async def list_my_notifications(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Notification]:
    result = await session.execute(
        select(Notification)
        .where(Notification.user_id == uuid.UUID(claims["sub"]))
        .order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Notification:
    notification = await session.get(Notification, notification_id)
    if notification is None or notification.user_id != uuid.UUID(claims["sub"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await session.commit()
    return notification
