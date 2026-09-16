import uuid
from datetime import UTC, datetime, timedelta

from tests.helpers import mint_token, seed_course, seed_course_offering, seed_program_and_term


def _slot(hour_offset: int = 0) -> tuple[str, str]:
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=10, hours=hour_offset)
    end = start + timedelta(hours=2)
    return start.isoformat(), end.isoformat()


async def test_non_overlapping_exam_schedules_succeed(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course_a = await seed_course(institution_id, program.id)
    course_b = await seed_course(institution_id, program.id)
    offering_a = await seed_course_offering(institution_id, course_a.id, term.id, instructor_id=uuid.uuid4(), room="A1")
    offering_b = await seed_course_offering(institution_id, course_b.id, term.id, instructor_id=uuid.uuid4(), room="A2")
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")

    starts_a, ends_a = _slot(0)
    starts_b, ends_b = _slot(5)

    first = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_a.id), "room": "Hall 1", "starts_at": starts_a, "ends_at": ends_a},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    second = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_b.id), "room": "Hall 2", "starts_at": starts_b, "ends_at": ends_b},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert first.status_code == 201
    assert second.status_code == 201


async def test_room_conflict_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course_a = await seed_course(institution_id, program.id)
    course_b = await seed_course(institution_id, program.id)
    offering_a = await seed_course_offering(institution_id, course_a.id, term.id, instructor_id=uuid.uuid4())
    offering_b = await seed_course_offering(institution_id, course_b.id, term.id, instructor_id=uuid.uuid4())
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    starts, ends = _slot(0)

    await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_a.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    response = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_b.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
    assert "room" in response.json()["detail"]


async def test_instructor_conflict_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course_a = await seed_course(institution_id, program.id)
    course_b = await seed_course(institution_id, program.id)
    shared_instructor = uuid.uuid4()
    offering_a = await seed_course_offering(institution_id, course_a.id, term.id, instructor_id=shared_instructor)
    offering_b = await seed_course_offering(institution_id, course_b.id, term.id, instructor_id=shared_instructor)
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")
    starts, ends = _slot(0)

    await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_a.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    response = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_b.id), "room": "Hall 2", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
    assert "instructor" in response.json()["detail"]


async def test_student_conflict_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course_a = await seed_course(institution_id, program.id)
    course_b = await seed_course(institution_id, program.id)
    offering_a = await seed_course_offering(institution_id, course_a.id, term.id, instructor_id=uuid.uuid4())
    offering_b = await seed_course_offering(institution_id, course_b.id, term.id, instructor_id=uuid.uuid4())
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")

    from tests.helpers import seed_enrollment

    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering_a.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering_b.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    starts, ends = _slot(0)
    await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_a.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    response = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering_b.id), "room": "Hall 2", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
    assert "student" in response.json()["detail"]


async def test_reschedule_to_a_free_slot_succeeds(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    admin_token = mint_token(tenant_id=str(institution_id), role="admin")

    starts, ends = _slot(0)
    create_resp = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    exam_id = create_resp.json()["id"]

    new_starts, new_ends = _slot(8)
    reschedule_resp = await client.put(
        f"/api/v1/academic/exam-schedules/{exam_id}",
        json={"course_offering_id": str(offering.id), "room": "Hall 1", "starts_at": new_starts, "ends_at": new_ends},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert reschedule_resp.status_code == 200
    assert reschedule_resp.json()["starts_at"].startswith(new_starts[:16])


async def test_exam_schedule_with_unknown_offering_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="admin")
    starts, ends = _slot(0)

    response = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(uuid.uuid4()), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_exam_schedule_rejects_inverted_time_range(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    token = mint_token(tenant_id=str(institution_id), role="admin")
    starts, ends = _slot(0)

    response = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering.id), "room": "Hall 1", "starts_at": ends, "ends_at": starts},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


async def test_non_owning_staff_cannot_schedule_exam(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    other_staff_token = mint_token(tenant_id=str(institution_id), role="lecturer")
    starts, ends = _slot(0)

    response = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {other_staff_token}"},
    )

    assert response.status_code == 403


async def test_duplicate_exam_schedule_for_same_offering_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    token = mint_token(tenant_id=str(institution_id), role="admin")
    starts, ends = _slot(0)
    await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {token}"},
    )

    starts2, ends2 = _slot(20)
    response = await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering.id), "room": "Hall 3", "starts_at": starts2, "ends_at": ends2},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


async def test_reschedule_unknown_exam_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="admin")
    starts, ends = _slot(0)

    response = await client.put(
        f"/api/v1/academic/exam-schedules/{uuid.uuid4()}",
        json={"course_offering_id": str(uuid.uuid4()), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_list_exam_schedules_for_term(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    token = mint_token(tenant_id=str(institution_id), role="admin")
    starts, ends = _slot(0)
    await client.post(
        "/api/v1/academic/exam-schedules",
        json={"course_offering_id": str(offering.id), "room": "Hall 1", "starts_at": starts, "ends_at": ends},
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.get(
        f"/api/v1/academic/exam-schedules?term_id={term.id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert len(response.json()) == 1

