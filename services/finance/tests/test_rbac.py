"""Role-enforcement (403) tests for finance. Deliberately assert on the role
gate ONLY - a rejected caller must never reach the business logic, so these
send minimal bodies and still expect 403, never 422.
"""
import uuid

from tests.helpers import mint_token


def _auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(role=role)}"}


async def test_student_cannot_create_a_fee_schedule(client) -> None:
    response = await client.post(
        "/api/v1/finance/fee-schedules",
        json={"program_id": str(uuid.uuid4()), "term_id": str(uuid.uuid4()), "amount_xaf": 450000},
        headers=_auth("student"),
    )
    assert response.status_code == 403


async def test_student_cannot_list_expenses(client) -> None:
    response = await client.get("/api/v1/finance/expenses", headers=_auth("student"))
    assert response.status_code == 403


async def test_student_cannot_record_an_expense(client) -> None:
    response = await client.post(
        "/api/v1/finance/expenses",
        json={"category": "misc", "amount_xaf": 1000, "description": "x"},
        headers=_auth("student"),
    )
    assert response.status_code == 403


async def test_student_cannot_list_campaigns(client) -> None:
    response = await client.get("/api/v1/finance/campaigns", headers=_auth("student"))
    assert response.status_code == 403


async def test_student_cannot_read_the_ledger(client) -> None:
    response = await client.get("/api/v1/finance/ledger-entries", headers=_auth("student"))
    assert response.status_code == 403


async def test_staff_cannot_regenerate_summaries_only_admin_can(client) -> None:
    """The one finance route deliberately narrower than the usual staff set."""
    response = await client.post(
        "/api/v1/finance/summaries/regenerate", json={"period": "2026-01-01"}, headers=_auth("staff")
    )
    assert response.status_code == 403


async def test_unauthenticated_cannot_list_expenses(client) -> None:
    response = await client.get("/api/v1/finance/expenses")
    assert response.status_code == 401


async def test_staff_is_allowed_past_the_role_gate_on_expenses(client) -> None:
    """Proves the 403s above are really about ROLE, not a blanket rejection."""
    response = await client.get("/api/v1/finance/expenses", headers=_auth("staff"))
    assert response.status_code == 200
