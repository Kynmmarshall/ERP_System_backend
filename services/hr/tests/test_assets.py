import uuid

from tests.helpers import mint_token


async def _create_asset(client, admin_token: str, *, total_quantity: int = 10) -> dict:
    response = await client.post(
        "/api/v1/hr/assets",
        json={"name": "Laptop", "category": "IT Equipment", "total_quantity": total_quantity},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    return response.json()


async def test_assigning_within_stock_succeeds(client) -> None:
    institution_id = uuid.uuid4()
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    asset = await _create_asset(client, admin_token)

    response = await client.post(
        "/api/v1/hr/assets/movements",
        json={
            "asset_id": asset["id"],
            "employee_id": str(uuid.uuid4()),
            "quantity_delta": 3,
            "reason": "Assigned for onboarding",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 201


async def test_assigning_more_than_on_hand_stock_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    asset = await _create_asset(client, admin_token, total_quantity=2)

    response = await client.post(
        "/api/v1/hr/assets/movements",
        json={
            "asset_id": asset["id"],
            "employee_id": str(uuid.uuid4()),
            "quantity_delta": 3,
            "reason": "Over-assign attempt",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409


async def test_return_movement_frees_up_on_hand_stock(client) -> None:
    institution_id = uuid.uuid4()
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    asset = await _create_asset(client, admin_token, total_quantity=2)
    employee_id = str(uuid.uuid4())

    assign_response = await client.post(
        "/api/v1/hr/assets/movements",
        json={"asset_id": asset["id"], "employee_id": employee_id, "quantity_delta": 2, "reason": "Assign all"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert assign_response.status_code == 201

    return_response = await client.post(
        "/api/v1/hr/assets/movements",
        json={"asset_id": asset["id"], "employee_id": employee_id, "quantity_delta": -1, "reason": "Partial return"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert return_response.status_code == 201

    reassign_response = await client.post(
        "/api/v1/hr/assets/movements",
        json={
            "asset_id": asset["id"],
            "employee_id": str(uuid.uuid4()),
            "quantity_delta": 1,
            "reason": "Assign returned unit",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reassign_response.status_code == 201


async def test_general_adjustment_below_assigned_quantity_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    asset = await _create_asset(client, admin_token, total_quantity=2)

    await client.post(
        "/api/v1/hr/assets/movements",
        json={
            "asset_id": asset["id"],
            "employee_id": str(uuid.uuid4()),
            "quantity_delta": 2,
            "reason": "Assign all",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    response = await client.post(
        "/api/v1/hr/assets/movements",
        json={"asset_id": asset["id"], "employee_id": None, "quantity_delta": -1, "reason": "Write-off attempt"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
