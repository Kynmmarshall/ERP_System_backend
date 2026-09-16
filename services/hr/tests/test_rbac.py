"""Role-enforcement (403) tests for hr - the service with the narrowest role
bands (several routes are super_admin-only because they release money).
Deliberately assert on the role gate ONLY: a rejected caller must never
reach the business logic, so these send minimal bodies and still expect 403.
"""
import uuid

from tests.helpers import mint_token


def _auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(role=role)}"}


async def test_student_cannot_reach_hr_at_all(client) -> None:
    for method, path in (
        ("get", "/api/v1/hr/positions"),
        ("get", "/api/v1/hr/assets"),
        ("get", "/api/v1/hr/leave/requests"),
        ("get", "/api/v1/hr/payroll/schedules"),
    ):
        response = await getattr(client, method)(path, headers=_auth("student"))
        assert response.status_code == 403, f"{method.upper()} {path} should be 403 for a student"


async def test_staff_cannot_do_hr_admin_work(client) -> None:
    for method, path in (
        ("get", "/api/v1/hr/leave/requests"),
        ("get", "/api/v1/hr/assets"),
        ("get", "/api/v1/hr/candidates"),
        ("get", "/api/v1/hr/payroll/schedules"),
    ):
        response = await getattr(client, method)(path, headers=_auth("lecturer"))
        assert response.status_code == 403, f"{method.upper()} {path} should be 403 for staff"


async def test_admin_cannot_verify_a_payroll_schedule_only_super_admin_can(client) -> None:
    """The statutory-rate release gate - deliberately above admin level."""
    response = await client.patch(
        f"/api/v1/hr/payroll/schedules/{uuid.uuid4()}/verify", headers=_auth("admin")
    )
    assert response.status_code == 403


async def test_staff_cannot_approve_a_payroll_run(client) -> None:
    response = await client.post(
        f"/api/v1/hr/payroll/runs/{uuid.uuid4()}/approve", headers=_auth("lecturer")
    )
    assert response.status_code == 403


async def test_admin_may_approve_a_payroll_run_but_only_after_a_super_admin_verified_the_rates(
    client,
) -> None:
    """Documents the real two-step control (Phase 6): approving a RUN is
    admin-level, but it is worthless until a super_admin has verified the
    rate schedule behind it. So admin must pass the role gate here (404 for
    an unknown run id, not 403) while still being blocked one level up.
    """
    response = await client.post(
        f"/api/v1/hr/payroll/runs/{uuid.uuid4()}/approve", headers=_auth("admin")
    )
    assert response.status_code == 404


async def test_student_cannot_check_in_to_a_shift(client) -> None:
    response = await client.post(
        "/api/v1/hr/attendance/check-in", json={"token": "x"}, headers=_auth("student")
    )
    assert response.status_code == 403


async def test_unauthenticated_cannot_list_positions(client) -> None:
    response = await client.get("/api/v1/hr/positions")
    assert response.status_code == 401


async def test_staff_is_allowed_past_the_role_gate_on_positions(client) -> None:
    """Proves the 403s above are really about ROLE, not a blanket rejection."""
    response = await client.get("/api/v1/hr/positions", headers=_auth("lecturer"))
    assert response.status_code == 200
