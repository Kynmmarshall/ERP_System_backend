import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.models.employees import Employee
from app.models.recruitment import Candidate, CandidateStage, Position, PositionStatus
from app.schemas import (
    CandidateCreateRequest,
    CandidateResponse,
    CandidateStageUpdateRequest,
    EmployeeResponse,
    HireRequest,
    PositionCreateRequest,
    PositionResponse,
)

router = APIRouter()

_HR_ADMIN_ROLES = ("admin",)
_STAFF_ROLES = ("admin", "lecturer", "finance_staff", "marketing")


@router.post("/positions", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
async def create_position(
    payload: PositionCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Position:
    position = Position(
        institution_id=uuid.UUID(claims["tenant_id"]),
        title=payload.title,
        department=payload.department,
        status=PositionStatus.OPEN,
    )
    session.add(position)
    await session.commit()
    return position


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Position]:
    result = await session.execute(select(Position).order_by(Position.created_at.desc()))
    return list(result.scalars().all())


@router.post("/positions/{position_id}/close", response_model=PositionResponse)
async def close_position(
    position_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Position:
    """Stops the position accepting new candidates. Anyone already in the
    pipeline keeps their stage and can still be hired.
    """
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    if position.status == PositionStatus.CLOSED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Position is already closed")

    position.status = PositionStatus.CLOSED
    await session.commit()
    return position


@router.post("/candidates", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    payload: CandidateCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Candidate:
    position = await session.get(Position, payload.position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    if position.status == PositionStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That position is closed and is no longer accepting candidates",
        )

    candidate = Candidate(
        institution_id=uuid.UUID(claims["tenant_id"]),
        position_id=payload.position_id,
        full_name=payload.full_name,
        email=payload.email,
        stage=CandidateStage.APPLIED,
    )
    session.add(candidate)
    await session.commit()
    return candidate


@router.get("/candidates", response_model=list[CandidateResponse])
async def list_candidates(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Candidate]:
    result = await session.execute(select(Candidate).order_by(Candidate.created_at.desc()))
    return list(result.scalars().all())


@router.patch("/candidates/{candidate_id}/stage", response_model=CandidateResponse)
async def update_candidate_stage(
    candidate_id: uuid.UUID,
    payload: CandidateStageUpdateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Candidate:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    try:
        candidate.stage = CandidateStage(payload.stage)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid stage") from exc
    await session.commit()
    return candidate


@router.post("/candidates/{candidate_id}/hire", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def hire_candidate(
    candidate_id: uuid.UUID,
    payload: HireRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Employee:
    """Atomically transitions a candidate to HIRED and creates their
    Employee profile. user_id is left null - provisioning an identity
    login for the new employee is a separate, out-of-band admin action.
    """
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    if candidate.stage == CandidateStage.HIRED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate already hired")

    employee = Employee(
        institution_id=uuid.UUID(claims["tenant_id"]),
        user_id=None,
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        email=candidate.email,
        department=payload.department,
        hire_date=payload.hire_date,
        gross_monthly_salary_xaf=payload.gross_monthly_salary_xaf,
    )
    candidate.stage = CandidateStage.HIRED
    session.add(employee)
    await session.commit()
    return employee


@router.get("/employees", response_model=list[EmployeeResponse])
async def list_employees(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Employee]:
    """Admin-only: the roster carries salary, so it stays above the staff band.
    Shift, review and asset-assignment forms all need this to resolve an
    employee_id without asking an admin to paste a UUID.
    """
    result = await session.execute(select(Employee).order_by(Employee.full_name))
    return list(result.scalars().all())
