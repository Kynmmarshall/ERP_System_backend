import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.models.summaries import FinancialSummary
from app.schemas import FinancialSummaryResponse, SummaryRegenerateRequest
from app.summaries import generate_summary

router = APIRouter()

_STAFF_ROLES = ("admin", "finance_staff")


@router.get("/summaries", response_model=list[FinancialSummaryResponse])
async def list_summaries(
    period: date | None = Query(default=None),
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[FinancialSummary]:
    query = select(FinancialSummary).order_by(FinancialSummary.period.desc(), FinancialSummary.version.desc())
    if period is not None:
        query = query.where(FinancialSummary.period == period)
    result = await session.execute(query)
    return list(result.scalars().all())


@router.post("/summaries/regenerate", response_model=FinancialSummaryResponse)
async def regenerate_summary(
    payload: SummaryRegenerateRequest,
    claims: dict = Depends(require_roles("admin",)),
    session: AsyncSession = Depends(get_tenant_session),
) -> FinancialSummary:
    summary = await generate_summary(session, institution_id=uuid.UUID(claims["tenant_id"]), period=payload.period)
    await session.commit()
    return summary
