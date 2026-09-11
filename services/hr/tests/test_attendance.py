import uuid
from datetime import UTC, datetime, timedelta

from tests.helpers import mint_token, seed_employee


async def _create_shift(client, admin_token: str, employee_id: uuid.UUID) -> dict:
    now = datetime.now(UTC)
    response = await client.post(
        "/api/v1/hr/attendance/shifts",
        json={
            "employee_id": str(employee_id),
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=8)).isoformat(),
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    return response.json()


async def test_check_in_succeeds_with_a_freshly_issued_token(client) -> None:
    institution_id = uuid.uuid4()
    user_id = uuid.uuid4()
    employee = await seed_employee(institution_id, user_id=user_id)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    staff_token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(user_id))

    shift = await _create_shift(client, admin_token, employee.id)
    qr_response = await client.post(
        f"/api/v1/hr/attendance/shifts/{shift['id']}/qr-token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert qr_response.status_code == 200
    token = qr_response.json()["token"]

    check_in_response = await client.post(
        "/api/v1/hr/attendance/check-in",
        json={"token": token},
        headers={"Authorization": f"Bearer {staff_token}"},
    )

    assert check_in_response.status_code == 201
    assert check_in_response.json()["employee_id"] == str(employee.id)


async def test_duplicate_check_in_for_the_same_shift_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    user_id = uuid.uuid4()
    employee = await seed_employee(institution_id, user_id=user_id)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    staff_token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(user_id))

    shift = await _create_shift(client, admin_token, employee.id)
    qr_response = await client.post(
        f"/api/v1/hr/attendance/shifts/{shift['id']}/qr-token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = qr_response.json()["token"]

    first = await client.post(
        "/api/v1/hr/attendance/check-in",
        json={"token": token},
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/hr/attendance/check-in",
        json={"token": token},
        headers={"Authorization": f"Bearer {staff_token}"},
    )

    assert second.status_code == 409


async def test_reissuing_a_qr_token_invalidates_the_previous_one(client) -> None:
    institution_id = uuid.uuid4()
    user_id = uuid.uuid4()
    employee = await seed_employee(institution_id, user_id=user_id)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    staff_token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(user_id))

    shift = await _create_shift(client, admin_token, employee.id)
    first_qr = await client.post(
        f"/api/v1/hr/attendance/shifts/{shift['id']}/qr-token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    stale_token = first_qr.json()["token"]

    await client.post(
        f"/api/v1/hr/attendance/shifts/{shift['id']}/qr-token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    response = await client.post(
        "/api/v1/hr/attendance/check-in",
        json={"token": stale_token},
        headers={"Authorization": f"Bearer {staff_token}"},
    )

    assert response.status_code == 401


async def test_check_in_rejects_a_shift_belonging_to_another_employee(client) -> None:
    institution_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    employee = await seed_employee(institution_id, user_id=owner_user_id, email="owner@example.com")
    await seed_employee(institution_id, user_id=other_user_id, email="other@example.com")
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    other_staff_token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(other_user_id))

    shift = await _create_shift(client, admin_token, employee.id)
    qr_response = await client.post(
        f"/api/v1/hr/attendance/shifts/{shift['id']}/qr-token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = qr_response.json()["token"]

    response = await client.post(
        "/api/v1/hr/attendance/check-in",
        json={"token": token},
        headers={"Authorization": f"Bearer {other_staff_token}"},
    )

    assert response.status_code == 403
