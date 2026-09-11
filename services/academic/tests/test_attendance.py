import uuid
from datetime import date

from tests.helpers import mint_token, seed_course, seed_course_offering, seed_program_and_term


async def test_instructor_can_create_session_and_mark_attendance(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")

    session_resp = await client.post(
        "/api/v1/academic/attendance-sessions",
        json={"course_offering_id": str(offering.id), "session_date": str(date.today())},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    student_id = uuid.uuid4()
    mark_resp = await client.post(
        f"/api/v1/academic/attendance-sessions/{session_id}/records",
        json={"records": [{"student_id": str(student_id), "present": True}]},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    assert mark_resp.status_code == 200
    assert mark_resp.json()[0]["present"] is True


async def test_non_owning_staff_cannot_manage_attendance(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    other_staff_token = mint_token(sub=str(uuid.uuid4()), tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/attendance-sessions",
        json={"course_offering_id": str(offering.id), "session_date": str(date.today())},
        headers={"Authorization": f"Bearer {other_staff_token}"},
    )

    assert response.status_code == 403


async def test_admin_bypasses_instructor_ownership_check(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")

    response = await client.post(
        "/api/v1/academic/attendance-sessions",
        json={"course_offering_id": str(offering.id), "session_date": str(date.today())},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 201


async def test_student_only_sees_own_attendance_record(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")

    session_resp = await client.post(
        "/api/v1/academic/attendance-sessions",
        json={"course_offering_id": str(offering.id), "session_date": str(date.today())},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    session_id = session_resp.json()["id"]

    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    await client.post(
        f"/api/v1/academic/attendance-sessions/{session_id}/records",
        json={
            "records": [
                {"student_id": str(student_a), "present": True},
                {"student_id": str(student_b), "present": False},
            ]
        },
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    student_a_token = mint_token(sub=str(student_a), tenant_id=str(institution_id), role="student")
    response = await client.get(
        f"/api/v1/academic/attendance-sessions/{session_id}/records",
        headers={"Authorization": f"Bearer {student_a_token}"},
    )

    assert response.status_code == 200
    records = response.json()
    assert len(records) == 1
    assert records[0]["student_id"] == str(student_a)


async def test_duplicate_session_for_same_date_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")
    payload = {"course_offering_id": str(offering.id), "session_date": str(date.today())}

    first = await client.post(
        "/api/v1/academic/attendance-sessions", json=payload, headers={"Authorization": f"Bearer {instructor_token}"}
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/academic/attendance-sessions", json=payload, headers={"Authorization": f"Bearer {instructor_token}"}
    )
    assert second.status_code == 409


async def test_session_with_unknown_offering_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="staff")

    response = await client.post(
        "/api/v1/academic/attendance-sessions",
        json={"course_offering_id": str(uuid.uuid4()), "session_date": str(date.today())},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_mark_attendance_on_unknown_session_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="staff")

    response = await client.post(
        f"/api/v1/academic/attendance-sessions/{uuid.uuid4()}/records",
        json={"records": [{"student_id": str(uuid.uuid4()), "present": True}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_marking_attendance_twice_updates_existing_record(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")
    session_id = (
        await client.post(
            "/api/v1/academic/attendance-sessions",
            json={"course_offering_id": str(offering.id), "session_date": str(date.today())},
            headers={"Authorization": f"Bearer {instructor_token}"},
        )
    ).json()["id"]
    student_id = uuid.uuid4()

    await client.post(
        f"/api/v1/academic/attendance-sessions/{session_id}/records",
        json={"records": [{"student_id": str(student_id), "present": False}]},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    second = await client.post(
        f"/api/v1/academic/attendance-sessions/{session_id}/records",
        json={"records": [{"student_id": str(student_id), "present": True}]},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    assert second.status_code == 200
    assert second.json()[0]["present"] is True


async def test_list_attendance_sessions_for_offering(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")
    await client.post(
        "/api/v1/academic/attendance-sessions",
        json={"course_offering_id": str(offering.id), "session_date": str(date.today())},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    response = await client.get(
        f"/api/v1/academic/attendance-sessions?course_offering_id={offering.id}",
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
