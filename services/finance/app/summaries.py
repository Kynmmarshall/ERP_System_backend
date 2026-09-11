import uuid
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.summaries import FinancialSummary


def month_start(value: date) -> date:
    return value.replace(day=1)


def add_month(value: date) -> date:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


async def compute_totals(session: AsyncSession, institution_id: uuid.UUID, period: date) -> tuple[int, int]:
    period_end = add_month(period)
    result = await session.execute(
        text(
            """
            SELECT
                COALESCE(SUM(amount_xaf) FILTER (
                    WHERE entry_type = 'TUITION_REVENUE' AND direction = 'CREDIT'
                ), 0) AS revenue,
                COALESCE(SUM(amount_xaf) FILTER (
                    WHERE entry_type = 'EXPENSE' AND direction = 'DEBIT'
                ), 0) AS expenses
            FROM ledger_entries
            WHERE institution_id = :institution_id AND created_at >= :period_start AND created_at < :period_end
            """
        ),
        {"institution_id": str(institution_id), "period_start": period, "period_end": period_end},
    )
    row = result.one()
    return row.revenue, row.expenses


async def generate_summary(session: AsyncSession, *, institution_id: uuid.UUID, period: date) -> FinancialSummary:
    """Always inserts a NEW row (version = previous max + 1) - regeneration
    never overwrites prior history, see phase5-plan.md.
    """
    existing = await session.execute(
        select(FinancialSummary.version)
        .where(FinancialSummary.institution_id == institution_id, FinancialSummary.period == period)
        .order_by(FinancialSummary.version.desc())
        .limit(1)
    )
    next_version = (existing.scalar_one_or_none() or 0) + 1

    revenue, expenses = await compute_totals(session, institution_id, period)
    summary = FinancialSummary(
        institution_id=institution_id,
        period=period,
        version=next_version,
        total_revenue_xaf=revenue,
        total_expenses_xaf=expenses,
        net_xaf=revenue - expenses,
    )
    session.add(summary)
    await session.flush()
    return summary


async def run_catch_up(session: AsyncSession) -> int:
    """Generates the missing version-1 summary for every fully-elapsed
    month (since an institution's first ledger activity) that doesn't
    have one yet. A missed scheduled run is simply "no row yet for that
    past period" - caught by this same idempotent check on the next tick.
    """
    institutions_result = await session.execute(text("SELECT DISTINCT institution_id FROM ledger_entries"))
    institution_ids = [row.institution_id for row in institutions_result.all()]
    created = 0
    current_month_start = month_start(date.today())

    for institution_id in institution_ids:
        earliest_result = await session.execute(
            text("SELECT MIN(created_at) AS earliest FROM ledger_entries WHERE institution_id = :institution_id"),
            {"institution_id": str(institution_id)},
        )
        earliest = earliest_result.scalar_one()
        if earliest is None:
            continue

        period = month_start(earliest.date())
        while period < current_month_start:
            exists_result = await session.execute(
                select(FinancialSummary.id).where(
                    FinancialSummary.institution_id == institution_id,
                    FinancialSummary.period == period,
                    FinancialSummary.version == 1,
                )
            )
            if exists_result.scalar_one_or_none() is None:
                await generate_summary(session, institution_id=institution_id, period=period)
                created += 1
            period = add_month(period)

    if created:
        await session.commit()
    return created
