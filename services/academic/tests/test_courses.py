import uuid

from tests.helpers import mint_token, seed_course, seed_course_offering, seed_enrollment, seed_program_and_term


async def test_staff_can_create_course(client) -> None:
    institution_id = uuid.uuid4()
    program, _ = await seed_program_and_term(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/courses",
        json={"program_id": str(program.id), "code": "CS101", "name": "Intro to CS", "credits": 4},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "CS101"
    assert body["credits"] == 4


async def test_student_cannot_create_course(client) -> None:
    institution_id = uuid.uuid4()
    program, _ = await seed_program_and_term(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/courses",
        json={"program_id": str(program.id), "code": "CS101", "name": "Intro to CS"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_prerequisite_cycle_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, _ = await seed_program_and_term(institution_id)
    course_a = await seed_course(institution_id, program.id)
    course_b = await seed_course(institution_id, program.id)
    token = mint_token(tenant_id=str(institution_id), role="staff")

    # A requires B
    first = await client.post(
        f"/api/v1/academic/courses/{course_a.id}/prerequisites",
        json={"prerequisite_course_id": str(course_b.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201

    # B requires A would close a cycle (A->B->A) - must be rejected
    second = await client.post(
        f"/api/v1/academic/courses/{course_b.id}/prerequisites",
        json={"prerequisite_course_id": str(course_a.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409


async def test_course_cannot_be_its_own_prerequisite(client) -> None:
    institution_id = uuid.uuid4()
    program, _ = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        f"/api/v1/academic/courses/{course.id}/prerequisites",
        json={"prerequisite_course_id": str(course.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


async def test_staff_can_create_course_offering(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/course-offerings",
        json={
            "course_id": str(course.id),
            "term_id": str(term.id),
            "instructor_id": str(instructor_id),
            "room": "B12",
            "capacity": 30,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["room"] == "B12"


async def test_registration_blocked_by_unmet_prerequisite(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    prerequisite_course = await seed_course(institution_id, program.id)
    main_course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    staff_token = mint_token(tenant_id=str(institution_id), role="staff")

    await client.post(
        f"/api/v1/academic/courses/{main_course.id}/prerequisites",
        json={"prerequisite_course_id": str(prerequisite_course.id)},
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    offering = await seed_course_offering(institution_id, main_course.id, term.id, instructor_id=instructor_id)

    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == 409
    assert str(prerequisite_course.id) in response.json()["detail"]["missing_course_ids"]


async def test_registration_succeeds_once_prerequisite_is_passed(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    prerequisite_course = await seed_course(institution_id, program.id)
    main_course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    staff_token = mint_token(tenant_id=str(institution_id), role="staff")

    await client.post(
        f"/api/v1/academic/courses/{main_course.id}/prerequisites",
        json={"prerequisite_course_id": str(prerequisite_course.id)},
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    prerequisite_offering = await seed_course_offering(
        institution_id, prerequisite_course.id, term.id, instructor_id=instructor_id
    )
    main_offering = await seed_course_offering(institution_id, main_course.id, term.id, instructor_id=instructor_id)

    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    # give the student a published passing grade in the prerequisite course
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")
    assessment_resp = await client.post(
        "/api/v1/academic/assessments",
        json={"course_offering_id": str(prerequisite_offering.id), "name": "Final", "max_score": 100},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    assessment_id = assessment_resp.json()["id"]
    await client.post(
        f"/api/v1/academic/assessments/{assessment_id}/grades",
        json={"grades": [{"student_id": str(student_id), "score": 80}]},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    await client.post(
        f"/api/v1/academic/assessments/{assessment_id}/publish",
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    response = await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(main_offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == 201


async def test_registration_rejects_wrong_term_offering(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    _, other_term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, other_term.id, instructor_id=instructor_id)

    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == 400


async def test_duplicate_registration_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)

    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    payload = {"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)}

    first = await client.post(
        "/api/v1/academic/course-registrations", json=payload, headers={"Authorization": f"Bearer {student_token}"}
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/academic/course-registrations", json=payload, headers={"Authorization": f"Bearer {student_token}"}
    )
    assert second.status_code == 409


async def test_create_course_with_unknown_program_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="staff")

    response = await client.post(
        "/api/v1/academic/courses",
        json={"program_id": str(uuid.uuid4()), "code": "X1", "name": "Unknown"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_list_courses_filters_by_program(client) -> None:
    institution_id = uuid.uuid4()
    program_a, _ = await seed_program_and_term(institution_id)
    program_b, _ = await seed_program_and_term(institution_id)
    course_a = await seed_course(institution_id, program_a.id)
    await seed_course(institution_id, program_b.id)
    token = mint_token(tenant_id=str(institution_id), role="student")

    response = await client.get(
        f"/api/v1/academic/courses?program_id={program_a.id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    codes = [row["code"] for row in response.json()]
    assert codes == [course_a.code]


async def test_prerequisite_on_unknown_course_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, _ = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        f"/api/v1/academic/courses/{uuid.uuid4()}/prerequisites",
        json={"prerequisite_course_id": str(course.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_list_prerequisites_returns_created_edge(client) -> None:
    institution_id = uuid.uuid4()
    program, _ = await seed_program_and_term(institution_id)
    course_a = await seed_course(institution_id, program.id)
    course_b = await seed_course(institution_id, program.id)
    token = mint_token(tenant_id=str(institution_id), role="staff")
    await client.post(
        f"/api/v1/academic/courses/{course_a.id}/prerequisites",
        json={"prerequisite_course_id": str(course_b.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.get(
        f"/api/v1/academic/courses/{course_a.id}/prerequisites", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()[0]["prerequisite_course_id"] == str(course_b.id)


async def test_course_offering_with_unknown_course_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    _, term = await seed_program_and_term(institution_id)
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/course-offerings",
        json={
            "course_id": str(uuid.uuid4()),
            "term_id": str(term.id),
            "instructor_id": str(uuid.uuid4()),
            "room": "A1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_course_offering_with_unknown_term_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, _ = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/course-offerings",
        json={
            "course_id": str(course.id),
            "term_id": str(uuid.uuid4()),
            "instructor_id": str(uuid.uuid4()),
            "room": "A1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_duplicate_course_offering_for_same_term_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/course-offerings",
        json={"course_id": str(course.id), "term_id": str(term.id), "instructor_id": str(uuid.uuid4()), "room": "A2"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


async def test_list_course_offerings_filters_by_term_and_course(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    token = mint_token(tenant_id=str(institution_id), role="student")

    response = await client.get(
        f"/api/v1/academic/course-offerings?term_id={term.id}&course_id={course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(offering.id)


async def test_staff_cannot_register_for_a_course(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    token = mint_token(tenant_id=str(institution_id), role="staff")

    response = await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_registration_with_someone_elses_enrollment_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    other_student_enrollment = await seed_enrollment(institution_id, uuid.uuid4(), program.id, term.id)
    student_token = mint_token(tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(other_student_enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == 404


async def test_registration_with_unknown_offering_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(uuid.uuid4()), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == 404


async def test_list_course_registrations_staff_sees_all_for_offering(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    staff_token = mint_token(tenant_id=str(institution_id), role="staff")
    response = await client.get(
        f"/api/v1/academic/course-registrations?course_offering_id={offering.id}",
        headers={"Authorization": f"Bearer {staff_token}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
