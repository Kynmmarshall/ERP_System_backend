import uuid

from tests.helpers import mint_token, seed_candidate, seed_position


async def test_admin_can_create_position(client) -> None:
    token = mint_token(role="admin")

    response = await client.post(
        "/api/v1/hr/positions",
        json={"title": "Lecturer", "department": "Computer Science"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "open"


async def test_staff_cannot_create_position(client) -> None:
    token = mint_token(role="lecturer")

    response = await client.post(
        "/api/v1/hr/positions",
        json={"title": "Lecturer", "department": "Computer Science"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_staff_can_list_positions(client) -> None:
    institution_id = uuid.uuid4()
    await seed_position(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="lecturer")

    response = await client.get("/api/v1/hr/positions", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_hire_candidate_creates_employee_and_marks_candidate_hired(client) -> None:
    institution_id = uuid.uuid4()
    position = await seed_position(institution_id)
    candidate = await seed_candidate(institution_id, position.id)
    token = mint_token(tenant_id=str(institution_id), role="admin")

    response = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/hire",
        json={
            "department": "Registry",
            "gross_monthly_salary_xaf": 400_000,
            "hire_date": "2024-06-01",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["candidate_id"] == str(candidate.id)
    assert body["gross_monthly_salary_xaf"] == 400_000

    candidates_response = await client.get("/api/v1/hr/candidates", headers={"Authorization": f"Bearer {token}"})
    assert candidates_response.json()[0]["stage"] == "hired"


async def test_hiring_already_hired_candidate_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    position = await seed_position(institution_id)
    candidate = await seed_candidate(institution_id, position.id)
    token = mint_token(tenant_id=str(institution_id), role="admin")
    hire_payload = {
        "department": "Registry",
        "gross_monthly_salary_xaf": 400_000,
        "hire_date": "2024-06-01",
    }
    await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/hire",
        json=hire_payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/hire",
        json=hire_payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


async def test_admin_can_list_employees(client) -> None:
    institution_id = uuid.uuid4()
    position = await seed_position(institution_id)
    candidate = await seed_candidate(institution_id, position.id)
    token = mint_token(tenant_id=str(institution_id), role="admin")
    await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/hire",
        json={
            "department": "Registry",
            "gross_monthly_salary_xaf": 400_000,
            "hire_date": "2024-06-01",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.get("/api/v1/hr/employees", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["full_name"] == candidate.full_name


async def test_staff_cannot_list_employees(client) -> None:
    token = mint_token(role="lecturer")

    response = await client.get("/api/v1/hr/employees", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


async def test_employee_roster_is_tenant_scoped(client) -> None:
    other_institution = uuid.uuid4()
    position = await seed_position(other_institution)
    candidate = await seed_candidate(other_institution, position.id)
    owner_token = mint_token(tenant_id=str(other_institution), role="admin")
    await client.post(
        f"/api/v1/hr/candidates/{candidate.id}/hire",
        json={
            "department": "Registry",
            "gross_monthly_salary_xaf": 400_000,
            "hire_date": "2024-06-01",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    outsider_token = mint_token(tenant_id=str(uuid.uuid4()), role="admin")

    response = await client.get(
        "/api/v1/hr/employees", headers={"Authorization": f"Bearer {outsider_token}"}
    )

    assert response.status_code == 200
    assert response.json() == []
