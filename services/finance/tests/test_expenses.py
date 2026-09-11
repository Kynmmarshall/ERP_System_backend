"""Expense + ledger tests. Require a real, migrated Postgres (see
readme.md)."""
import uuid

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.ledger import LedgerDirection, LedgerEntry
from tests.helpers import mint_token


async def test_admin_can_create_expense_and_it_posts_a_balanced_ledger_entry(client) -> None:
    institution_id = uuid.uuid4()
    token = mint_token(tenant_id=str(institution_id), role="admin")

    response = await client.post(
        "/api/v1/finance/expenses",
        json={"category": "utilities", "amount_xaf": 25_000, "description": "Electricity bill"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    expense_id = uuid.UUID(response.json()["id"])

    async with SessionFactory() as session:
        await set_platform_context(session)
        entries = (
            (await session.execute(select(LedgerEntry).where(LedgerEntry.reference_id == expense_id))).scalars().all()
        )
        assert len(entries) == 2
        debit_total = sum(e.amount_xaf for e in entries if e.direction == LedgerDirection.DEBIT)
        credit_total = sum(e.amount_xaf for e in entries if e.direction == LedgerDirection.CREDIT)
        assert debit_total == credit_total == 25_000


async def test_student_cannot_create_expense(client) -> None:
    token = mint_token(role="student")

    response = await client.post(
        "/api/v1/finance/expenses",
        json={"category": "utilities", "amount_xaf": 25_000, "description": "Electricity bill"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_list_expenses_returns_created_expense(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="staff")
    await client.post(
        "/api/v1/finance/expenses",
        json={"category": "supplies", "amount_xaf": 5_000, "description": "Stationery"},
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.get("/api/v1/finance/expenses", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["category"] == "supplies"
