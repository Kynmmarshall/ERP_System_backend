"""Financial summary tests. Require a real, migrated Postgres (see
readme.md)."""
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.ledger import LedgerLine, post_balanced
from app.models.ledger import LedgerDirection, LedgerEntry, LedgerEntryType
from app.models.summaries import FinancialSummary
from app.summaries import add_month, generate_summary, run_catch_up
from tests.helpers import mint_token


async def _post_revenue_and_expense(institution_id: uuid.UUID, *, created_at: datetime, revenue: int, expense: int) -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)
        await post_balanced(
            session,
            institution_id=institution_id,
            lines=[
                LedgerLine(LedgerEntryType.CASH, LedgerDirection.DEBIT, revenue, "invoice", uuid.uuid4()),
                LedgerLine(LedgerEntryType.TUITION_REVENUE, LedgerDirection.CREDIT, revenue, "invoice", uuid.uuid4()),
            ],
            description="test revenue",
        )
        await post_balanced(
            session,
            institution_id=institution_id,
            lines=[
                LedgerLine(LedgerEntryType.EXPENSE, LedgerDirection.DEBIT, expense, "expense", uuid.uuid4()),
                LedgerLine(LedgerEntryType.CASH, LedgerDirection.CREDIT, expense, "expense", uuid.uuid4()),
            ],
            description="test expense",
        )
        await session.commit()

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(LedgerEntry).where(LedgerEntry.institution_id == institution_id).order_by(LedgerEntry.created_at.desc()).limit(4)
        )
        for entry in result.scalars().all():
            entry.created_at = created_at
        await session.commit()


async def test_generate_summary_computes_revenue_expenses_and_net() -> None:
    institution_id = uuid.uuid4()
    period = date(2026, 6, 1)
    await _post_revenue_and_expense(
        institution_id, created_at=datetime(2026, 6, 15, tzinfo=UTC), revenue=450_000, expense=50_000
    )

    async with SessionFactory() as session:
        await set_platform_context(session)
        summary = await generate_summary(session, institution_id=institution_id, period=period)
        await session.commit()

    assert summary.version == 1
    assert summary.total_revenue_xaf == 450_000
    assert summary.total_expenses_xaf == 50_000
    assert summary.net_xaf == 400_000


async def test_regenerate_creates_a_new_version_without_deleting_the_old_one(client) -> None:
    institution_id = uuid.uuid4()
    period = date(2026, 7, 1)
    await _post_revenue_and_expense(
        institution_id, created_at=datetime(2026, 7, 10, tzinfo=UTC), revenue=100_000, expense=10_000
    )
    token = mint_token(tenant_id=str(institution_id), role="admin")

    first = await client.post(
        "/api/v1/finance/summaries/regenerate",
        json={"period": str(period)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.json()["version"] == 1

    second = await client.post(
        "/api/v1/finance/summaries/regenerate",
        json={"period": str(period)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.json()["version"] == 2

    listing = await client.get(
        f"/api/v1/finance/summaries?period={period}", headers={"Authorization": f"Bearer {token}"}
    )
    assert len(listing.json()) == 2


async def test_catch_up_generates_missing_past_month_summary() -> None:
    institution_id = uuid.uuid4()
    past_period = date(2026, 3, 1)
    await _post_revenue_and_expense(
        institution_id, created_at=datetime(2026, 3, 5, tzinfo=UTC), revenue=200_000, expense=0
    )

    async with SessionFactory() as session:
        await set_platform_context(session)
        created = await run_catch_up(session)
        assert created >= 1

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(FinancialSummary).where(
                FinancialSummary.institution_id == institution_id, FinancialSummary.period == past_period
            )
        )
        summary = result.scalar_one()
        assert summary.total_revenue_xaf == 200_000


def test_add_month_rolls_over_december() -> None:
    assert add_month(date(2026, 12, 1)) == date(2027, 1, 1)
