import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.models.employees import Employee
from app.models.performance import PerformanceReview
from app.schemas import PerformanceReviewCreateRequest, PerformanceReviewResponse

router = APIRouter()

_HR_ADMIN_ROLES = ("admin", "super_admin")
_STAFF_ROLES = ("admin", "staff", "lecturer", "finance_staff", "super_admin")


@router.post("/performance/reviews", response_model=PerformanceReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_performance_review(
    payload: PerformanceReviewCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> PerformanceReview:
    employee = await session.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    review = PerformanceReview(
        institution_id=uuid.UUID(claims["tenant_id"]),
        employee_id=payload.employee_id,
        reviewer_id=uuid.UUID(claims["sub"]),
        period=payload.period,
        rating=payload.rating,
        comments=payload.comments,
    )
    session.add(review)
    await session.commit()
    return review


@router.get("/performance/reviews", response_model=list[PerformanceReviewResponse])
async def list_performance_reviews(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[PerformanceReview]:
    result = await session.execute(select(PerformanceReview).order_by(PerformanceReview.created_at.desc()))
    return list(result.scalars().all())


@router.get("/performance/reviews/mine", response_model=list[PerformanceReviewResponse])
async def list_my_performance_reviews(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[PerformanceReview]:
    result = await session.execute(select(Employee).where(Employee.user_id == uuid.UUID(claims["sub"])))
    employee = result.scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account")
    reviews = await session.execute(
        select(PerformanceReview)
        .where(PerformanceReview.employee_id == employee.id)
        .order_by(PerformanceReview.created_at.desc())
    )
    return list(reviews.scalars().all())
