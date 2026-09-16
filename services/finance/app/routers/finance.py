import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_claims, get_tenant_session, require_roles
from app.models.finance import FeeSchedule, Invoice
from app.schemas import FeeScheduleCreateRequest, FeeScheduleResponse, InvoiceResponse

router = APIRouter()


@router.post(
    "/fee-schedules",
    response_model=FeeScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin", "staff", "finance_staff", "super_admin"))],
)
async def create_fee_schedule(
    payload: FeeScheduleCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> FeeSchedule:
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")

    fee_schedule = FeeSchedule(
        institution_id=uuid.UUID(tenant_id),
        program_id=payload.program_id,
        term_id=payload.term_id,
        amount_xaf=payload.amount_xaf,
    )
    session.add(fee_schedule)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Fee schedule already exists for this program/term"
        ) from exc
    return fee_schedule


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    enrollment_id: uuid.UUID | None = Query(default=None),
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Invoice]:
    query = select(Invoice).order_by(Invoice.created_at.desc())
    if claims.get("role") == "student":
        query = query.where(Invoice.student_id == uuid.UUID(claims["sub"]))
    if enrollment_id is not None:
        query = query.where(Invoice.enrollment_id == enrollment_id)
    result = await session.execute(query)
    return list(result.scalars().all())


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> Invoice:
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    if claims.get("role") == "student" and invoice.student_id != uuid.UUID(claims["sub"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice
