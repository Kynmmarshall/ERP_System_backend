import uuid

from tests.helpers import mint_token, seed_employee, seed_schedule_version


async def test_generating_a_run_creates_payslips_for_active_employees(client) -> None:
    institution_id = uuid.uuid4()
    employee = await seed_employee(institution_id, gross_monthly_salary_xaf=500_000)
    schedule = await seed_schedule_version(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="admin")

    response = await client.post(
        "/api/v1/hr/payroll/runs",
        json={"period": "2024-06-01", "schedule_version_id": str(schedule.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    run_id = response.json()["id"]

    payslips_response = await client.get(
        f"/api/v1/hr/payroll/runs/{run_id}/payslips", headers={"Authorization": f"Bearer {token}"}
    )
    assert payslips_response.status_code == 200
    payslips = payslips_response.json()
    assert len(payslips) == 1
    assert payslips[0]["employee_id"] == str(employee.id)
    assert payslips[0]["gross_xaf"] == 500_000
    assert payslips[0]["net_xaf"] == 500_000 - payslips[0]["cnps_employee_xaf"] - payslips[0]["irpp_xaf"]


async def test_generating_a_second_run_for_the_same_period_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    await seed_employee(institution_id)
    schedule = await seed_schedule_version(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="admin")
    payload = {"period": "2024-06-01", "schedule_version_id": str(schedule.id)}

    first = await client.post("/api/v1/hr/payroll/runs", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert first.status_code == 201

    second = await client.post("/api/v1/hr/payroll/runs", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert second.status_code == 409


async def test_approving_a_run_backed_by_an_unverified_schedule_is_blocked(client) -> None:
    institution_id = uuid.uuid4()
    await seed_employee(institution_id)
    schedule = await seed_schedule_version(institution_id, is_verified=False)
    token = mint_token(tenant_id=str(institution_id), role="admin")

    run_response = await client.post(
        "/api/v1/hr/payroll/runs",
        json={"period": "2024-06-01", "schedule_version_id": str(schedule.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    run_id = run_response.json()["id"]

    response = await client.post(
        f"/api/v1/hr/payroll/runs/{run_id}/approve", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403


async def test_approving_a_run_backed_by_a_verified_schedule_succeeds(client) -> None:
    institution_id = uuid.uuid4()
    admin_user_id = uuid.uuid4()
    employee_user_id = uuid.uuid4()
    await seed_employee(institution_id, user_id=employee_user_id)
    schedule = await seed_schedule_version(institution_id, is_verified=False)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin", sub=str(admin_user_id))
    super_admin_token = mint_token(tenant_id=str(institution_id), role="super_admin")
    employee_token = mint_token(tenant_id=str(institution_id), role="lecturer", sub=str(employee_user_id))

    run_response = await client.post(
        "/api/v1/hr/payroll/runs",
        json={"period": "2024-06-01", "schedule_version_id": str(schedule.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    run_id = run_response.json()["id"]

    verify_response = await client.patch(
        f"/api/v1/hr/payroll/schedules/{schedule.id}/verify",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["is_verified"] is True

    approve_response = await client.post(
        f"/api/v1/hr/payroll/runs/{run_id}/approve", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    payslips_response = await client.get(
        "/api/v1/hr/payroll/payslips/mine", headers={"Authorization": f"Bearer {employee_token}"}
    )
    assert payslips_response.status_code == 200
    assert len(payslips_response.json()) == 1


async def test_staff_cannot_see_payslips_from_a_draft_run(client) -> None:
    institution_id = uuid.uuid4()
    employee_user_id = uuid.uuid4()
    await seed_employee(institution_id, user_id=employee_user_id)
    schedule = await seed_schedule_version(institution_id)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    employee_token = mint_token(tenant_id=str(institution_id), role="lecturer", sub=str(employee_user_id))

    await client.post(
        "/api/v1/hr/payroll/runs",
        json={"period": "2024-06-01", "schedule_version_id": str(schedule.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    response = await client.get(
        "/api/v1/hr/payroll/payslips/mine", headers={"Authorization": f"Bearer {employee_token}"}
    )

    assert response.status_code == 200
    assert response.json() == []
