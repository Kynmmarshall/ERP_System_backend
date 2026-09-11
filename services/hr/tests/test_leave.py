import uuid

from tests.helpers import mint_token, seed_employee


async def test_staff_can_create_and_list_own_leave_request(client) -> None:
    institution_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await seed_employee(institution_id, user_id=user_id)
    token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(user_id))

    create_response = await client.post(
        "/api/v1/hr/leave/requests",
        json={"starts_on": "2024-07-01", "ends_on": "2024-07-05", "reason": "Family event"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["status"] == "pending"

    mine_response = await client.get("/api/v1/hr/leave/requests/mine", headers={"Authorization": f"Bearer {token}"})
    assert mine_response.status_code == 200
    assert len(mine_response.json()) == 1


async def test_admin_can_approve_leave_and_it_creates_a_notification(client) -> None:
    institution_id = uuid.uuid4()
    requester_user_id = uuid.uuid4()
    admin_user_id = uuid.uuid4()
    await seed_employee(institution_id, user_id=requester_user_id)
    requester_token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(requester_user_id))
    admin_token = mint_token(tenant_id=str(institution_id), role="admin", sub=str(admin_user_id))

    create_response = await client.post(
        "/api/v1/hr/leave/requests",
        json={"starts_on": "2024-07-01", "ends_on": "2024-07-05", "reason": "Family event"},
        headers={"Authorization": f"Bearer {requester_token}"},
    )
    request_id = create_response.json()["id"]

    decision_response = await client.post(
        f"/api/v1/hr/leave/requests/{request_id}/decision",
        json={"approve": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "approved"

    notifications_response = await client.get(
        "/api/v1/hr/notifications/mine", headers={"Authorization": f"Bearer {requester_token}"}
    )
    assert notifications_response.status_code == 200
    assert len(notifications_response.json()) == 1
    assert "approved" in notifications_response.json()[0]["message"]


async def test_admin_cannot_approve_their_own_leave_request(client) -> None:
    institution_id = uuid.uuid4()
    admin_user_id = uuid.uuid4()
    await seed_employee(institution_id, user_id=admin_user_id)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin", sub=str(admin_user_id))

    create_response = await client.post(
        "/api/v1/hr/leave/requests",
        json={"starts_on": "2024-07-01", "ends_on": "2024-07-05", "reason": "Family event"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    request_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/hr/leave/requests/{request_id}/decision",
        json={"approve": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 403


async def test_deciding_an_already_decided_request_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    requester_user_id = uuid.uuid4()
    await seed_employee(institution_id, user_id=requester_user_id)
    requester_token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(requester_user_id))
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")

    create_response = await client.post(
        "/api/v1/hr/leave/requests",
        json={"starts_on": "2024-07-01", "ends_on": "2024-07-05", "reason": "Family event"},
        headers={"Authorization": f"Bearer {requester_token}"},
    )
    request_id = create_response.json()["id"]

    await client.post(
        f"/api/v1/hr/leave/requests/{request_id}/decision",
        json={"approve": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    response = await client.post(
        f"/api/v1/hr/leave/requests/{request_id}/decision",
        json={"approve": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
