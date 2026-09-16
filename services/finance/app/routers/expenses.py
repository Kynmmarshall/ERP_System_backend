import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.ledger import LedgerLine, post_balanced
from app.models.ledger import Expense, LedgerDirection, LedgerEntry, LedgerEntryType
from app.schemas import ExpenseCreateRequest, ExpenseResponse, LedgerEntryResponse

router = APIRouter()

_STAFF_ROLES = ("admin", "finance_staff", "super_admin")


@router.post(
    "/expenses",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_expense(
    payload: ExpenseCreateRequest,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Expense:
    institution_id = uuid.UUID(claims["tenant_id"])
    expense = Expense(
        institution_id=institution_id,
        category=payload.category,
        amount_xaf=payload.amount_xaf,
        description=payload.description,
        recorded_by=uuid.UUID(claims["sub"]),
    )
    session.add(expense)
    await session.flush()

    await post_balanced(
        session,
        institution_id=institution_id,
        lines=[
            LedgerLine(LedgerEntryType.EXPENSE, LedgerDirection.DEBIT, expense.amount_xaf, "expense", expense.id),
            LedgerLine(LedgerEntryType.CASH, LedgerDirection.CREDIT, expense.amount_xaf, "expense", expense.id),
        ],
        description=f"Expense: {expense.category}",
    )
    await session.commit()
    return expense


@router.get("/expenses", response_model=list[ExpenseResponse])
async def list_expenses(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Expense]:
    result = await session.execute(select(Expense).order_by(Expense.created_at.desc()))
    return list(result.scalars().all())


@router.get("/ledger-entries", response_model=list[LedgerEntryResponse])
async def list_ledger_entries(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[LedgerEntry]:
    result = await session.execute(select(LedgerEntry).order_by(LedgerEntry.created_at.desc()))
    return list(result.scalars().all())
