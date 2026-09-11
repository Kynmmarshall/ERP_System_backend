import uuid

from tests.helpers import mint_token, seed_employee


async def test_admin_can_create_performance_review(client) -> None:
    institution_id = uuid.uuid4()
    employee = await seed_employee(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="admin")

    response = await client.post(
        "/api/v1/hr/performance/reviews",
        json={
            "employee_id": str(employee.id),
            "period": "2024-06-30",
            "rating": 4,
            "comments": "Solid quarter.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["rating"] == 4


async def test_staff_cannot_create_performance_review(client) -> None:
    institution_id = uuid.uuid4()
    employee = await seed_employee(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/hr/performance/reviews",
        json={
            "employee_id": str(employee.id),
            "period": "2024-06-30",
            "rating": 4,
            "comments": "Solid quarter.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_rating_out_of_range_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    employee = await seed_employee(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="admin")

    response = await client.post(
        "/api/v1/hr/performance/reviews",
        json={
            "employee_id": str(employee.id),
            "period": "2024-06-30",
            "rating": 6,
            "comments": "Invalid rating.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


async def test_staff_can_list_only_their_own_reviews(client) -> None:
    institution_id = uuid.uuid4()
    user_id = uuid.uuid4()
    own_employee = await seed_employee(institution_id, user_id=user_id, email="own@example.com")
    other_employee = await seed_employee(institution_id, email="other@example.com")
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    staff_token = mint_token(tenant_id=str(institution_id), role="staff", sub=str(user_id))

    for employee in (own_employee, other_employee):
        await client.post(
            "/api/v1/hr/performance/reviews",
            json={
                "employee_id": str(employee.id),
                "period": "2024-06-30",
                "rating": 3,
                "comments": "Review.",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    response = await client.get(
        "/api/v1/hr/performance/reviews/mine", headers={"Authorization": f"Bearer {staff_token}"}
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["employee_id"] == str(own_employee.id)
