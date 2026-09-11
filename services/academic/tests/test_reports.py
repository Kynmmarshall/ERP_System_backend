import uuid
from datetime import date, timedelta

from tests.helpers import mint_token, seed_course, seed_course_offering, seed_enrollment, seed_program_and_term


async def test_at_risk_status_is_unknown_with_no_data(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")

    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    response = await client.get(
        f"/api/v1/academic/course-offerings/{offering.id}/at-risk",
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["attendance_rate"] is None
    assert body[0]["assessment_average"] is None
    assert body[0]["at_risk"] is False


async def test_at_risk_true_when_attendance_below_threshold(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")

    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    # 1 present out of 4 sessions = 25% < 75% threshold
    for i in range(4):
        session_resp = await client.post(
            "/api/v1/academic/attendance-sessions",
            json={"course_offering_id": str(offering.id), "session_date": str(date.today() - timedelta(days=i))},
            headers={"Authorization": f"Bearer {instructor_token}"},
        )
        session_id = session_resp.json()["id"]
        await client.post(
            f"/api/v1/academic/attendance-sessions/{session_id}/records",
            json={"records": [{"student_id": str(student_id), "present": i == 0}]},
            headers={"Authorization": f"Bearer {instructor_token}"},
        )

    response = await client.get(
        f"/api/v1/academic/course-offerings/{offering.id}/at-risk",
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    body = response.json()[0]
    assert body["attendance_rate"] == 0.25
    assert body["at_risk"] is True


async def test_at_risk_true_when_latest_two_assessments_below_pass_threshold(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="staff")
    student_id = uuid.uuid4()

    for name, score in (("Quiz 1", 30), ("Quiz 2", 40)):
        assessment_resp = await client.post(
            "/api/v1/academic/assessments",
            json={"course_offering_id": str(offering.id), "name": name, "max_score": 100},
            headers={"Authorization": f"Bearer {instructor_token}"},
        )
        assessment_id = assessment_resp.json()["id"]
        await client.post(
            f"/api/v1/academic/assessments/{assessment_id}/grades",
            json={"grades": [{"student_id": str(student_id), "score": score}]},
            headers={"Authorization": f"Bearer {instructor_token}"},
        )
        await client.post(
            f"/api/v1/academic/assessments/{assessment_id}/publish",
            headers={"Authorization": f"Bearer {instructor_token}"},
        )

    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    response = await client.get(
        f"/api/v1/academic/course-offerings/{offering.id}/at-risk",
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    body = response.json()[0]
    assert body["assessment_average"] == 35.0
    assert body["at_risk"] is True


async def test_transcript_pdf_is_returned(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    response = await client.get(
        "/api/v1/academic/reports/transcript", headers={"Authorization": f"Bearer {student_token}"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


async def test_student_cannot_request_another_students_transcript(client) -> None:
    institution_id = uuid.uuid4()
    student_token = mint_token(tenant_id=str(institution_id), role="student")

    response = await client.get(
        f"/api/v1/academic/reports/transcript?student_id={uuid.uuid4()}",
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == 403


async def test_attendance_summary_pdf_is_returned(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    student_id = uuid.uuid4()
    enrollment = await seed_enrollment(institution_id, student_id, program.id, term.id)
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    await client.post(
        "/api/v1/academic/course-registrations",
        json={"course_offering_id": str(offering.id), "enrollment_id": str(enrollment.id)},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    response = await client.get(
        "/api/v1/academic/reports/attendance-summary", headers={"Authorization": f"Bearer {student_token}"}
    )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
