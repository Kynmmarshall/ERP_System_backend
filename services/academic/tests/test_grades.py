import uuid

from tests.helpers import mint_token, seed_course, seed_course_offering, seed_program_and_term


async def _seed_offering_with_grade(client, *, score: float = 40):
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="lecturer")
    student_id = uuid.uuid4()
    student_token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    assessment_resp = await client.post(
        "/api/v1/academic/assessments",
        json={"course_offering_id": str(offering.id), "name": "Midterm", "max_score": 100},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    assessment_id = assessment_resp.json()["id"]
    await client.post(
        f"/api/v1/academic/assessments/{assessment_id}/grades",
        json={"grades": [{"student_id": str(student_id), "score": score}]},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    return {
        "institution_id": institution_id,
        "instructor_token": instructor_token,
        "student_token": student_token,
        "student_id": student_id,
        "assessment_id": assessment_id,
    }


async def test_grade_out_of_range_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    instructor_token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="lecturer")

    assessment_resp = await client.post(
        "/api/v1/academic/assessments",
        json={"course_offering_id": str(offering.id), "name": "Quiz", "max_score": 20},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )
    assessment_id = assessment_resp.json()["id"]

    response = await client.post(
        f"/api/v1/academic/assessments/{assessment_id}/grades",
        json={"grades": [{"student_id": str(uuid.uuid4()), "score": 25}]},
        headers={"Authorization": f"Bearer {instructor_token}"},
    )

    assert response.status_code == 400


async def test_student_cannot_see_unpublished_grade(client) -> None:
    ctx = await _seed_offering_with_grade(client)

    response = await client.get(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_student_sees_grade_once_published(client) -> None:
    ctx = await _seed_offering_with_grade(client, score=72)

    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )

    response = await client.get(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert float(body[0]["score"]) == 72
    assert body[0]["published"] is True


async def test_appeal_full_lifecycle_accepted_updates_score_and_audit_log(client) -> None:
    ctx = await _seed_offering_with_grade(client, score=40)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grades = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()
    grade_id = grades[0]["id"]

    appeal_resp = await client.post(
        f"/api/v1/academic/grades/{grade_id}/appeals",
        json={"reason": "Miscounted question 4"},
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )
    assert appeal_resp.status_code == 201
    appeal_id = appeal_resp.json()["id"]
    assert appeal_resp.json()["status"] == "submitted"

    review_resp = await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "under_review"},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    assert review_resp.status_code == 200
    assert review_resp.json()["status"] == "under_review"

    decision_resp = await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "accepted", "reviewer_notes": "Confirmed miscount", "corrected_score": 55},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["status"] == "accepted"

    updated_grades = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()
    assert float(updated_grades[0]["score"]) == 55


async def test_rejected_appeal_leaves_score_unchanged(client) -> None:
    ctx = await _seed_offering_with_grade(client, score=40)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grades = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()
    grade_id = grades[0]["id"]

    appeal_id = (
        await client.post(
            f"/api/v1/academic/grades/{grade_id}/appeals",
            json={"reason": "Please recheck"},
            headers={"Authorization": f"Bearer {ctx['student_token']}"},
        )
    ).json()["id"]

    decision_resp = await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "rejected", "reviewer_notes": "Grading was correct"},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["status"] == "rejected"

    updated_grades = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()
    assert float(updated_grades[0]["score"]) == 40


async def test_cannot_appeal_unpublished_grade(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    grades = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()
    grade_id = grades[0]["id"]

    response = await client.post(
        f"/api/v1/academic/grades/{grade_id}/appeals",
        json={"reason": "too early"},
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )

    assert response.status_code == 400


async def test_other_student_cannot_appeal_someone_elses_grade(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grades = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()
    grade_id = grades[0]["id"]

    other_student_token = mint_token(
        sub=str(uuid.uuid4()), tenant_id=str(ctx["institution_id"]), role="student"
    )
    response = await client.post(
        f"/api/v1/academic/grades/{grade_id}/appeals",
        json={"reason": "not mine"},
        headers={"Authorization": f"Bearer {other_student_token}"},
    )

    assert response.status_code == 404


async def test_create_assessment_with_unknown_offering_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="lecturer")

    response = await client.post(
        "/api/v1/academic/assessments",
        json={"course_offering_id": str(uuid.uuid4()), "name": "Quiz"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_non_owning_staff_cannot_create_assessment(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=uuid.uuid4())
    other_staff_token = mint_token(tenant_id=str(institution_id), role="lecturer")

    response = await client.post(
        "/api/v1/academic/assessments",
        json={"course_offering_id": str(offering.id), "name": "Quiz"},
        headers={"Authorization": f"Bearer {other_staff_token}"},
    )

    assert response.status_code == 403


async def test_list_assessments_for_offering(client) -> None:
    institution_id = uuid.uuid4()
    program, term = await seed_program_and_term(institution_id)
    course = await seed_course(institution_id, program.id)
    instructor_id = uuid.uuid4()
    offering = await seed_course_offering(institution_id, course.id, term.id, instructor_id=instructor_id)
    token = mint_token(sub=str(instructor_id), tenant_id=str(institution_id), role="lecturer")
    await client.post(
        "/api/v1/academic/assessments",
        json={"course_offering_id": str(offering.id), "name": "Quiz"},
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.get(
        f"/api/v1/academic/assessments?course_offering_id={offering.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_enter_grades_with_unknown_assessment_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="lecturer")

    response = await client.post(
        f"/api/v1/academic/assessments/{uuid.uuid4()}/grades",
        json={"grades": [{"student_id": str(uuid.uuid4()), "score": 50}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_publish_with_unknown_assessment_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="lecturer")

    response = await client.post(
        f"/api/v1/academic/assessments/{uuid.uuid4()}/publish", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


async def test_staff_sees_unpublished_grades(client) -> None:
    ctx = await _seed_offering_with_grade(client, score=61)

    response = await client.get(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["published"] is False


async def test_appeal_on_unknown_grade_is_rejected(client) -> None:
    student_token = mint_token(tenant_id=str(uuid.uuid4()), role="student")

    response = await client.post(
        f"/api/v1/academic/grades/{uuid.uuid4()}/appeals",
        json={"reason": "n/a"},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == 404


async def test_cannot_submit_second_open_appeal(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grade_id = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()[0]["id"]

    first = await client.post(
        f"/api/v1/academic/grades/{grade_id}/appeals",
        json={"reason": "first"},
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/academic/grades/{grade_id}/appeals",
        json={"reason": "second"},
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )
    assert second.status_code == 409


async def test_list_appeals_owner_and_non_owner(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grade_id = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()[0]["id"]
    await client.post(
        f"/api/v1/academic/grades/{grade_id}/appeals",
        json={"reason": "first"},
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )

    owner_resp = await client.get(
        f"/api/v1/academic/grades/{grade_id}/appeals", headers={"Authorization": f"Bearer {ctx['student_token']}"}
    )
    assert owner_resp.status_code == 200
    assert len(owner_resp.json()) == 1

    other_student_token = mint_token(tenant_id=str(ctx["institution_id"]), role="student")
    other_resp = await client.get(
        f"/api/v1/academic/grades/{grade_id}/appeals", headers={"Authorization": f"Bearer {other_student_token}"}
    )
    assert other_resp.status_code == 404


async def test_decide_appeal_requires_staff_role(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    response = await client.post(
        f"/api/v1/academic/appeals/{uuid.uuid4()}/decision",
        json={"status": "under_review"},
        headers={"Authorization": f"Bearer {ctx['student_token']}"},
    )
    assert response.status_code == 403


async def test_decide_unknown_appeal_is_rejected(client) -> None:
    token = mint_token(tenant_id=str(uuid.uuid4()), role="admin")

    response = await client.post(
        f"/api/v1/academic/appeals/{uuid.uuid4()}/decision",
        json={"status": "under_review"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_decide_appeal_invalid_status_string_is_rejected(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grade_id = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()[0]["id"]
    appeal_id = (
        await client.post(
            f"/api/v1/academic/grades/{grade_id}/appeals",
            json={"reason": "x"},
            headers={"Authorization": f"Bearer {ctx['student_token']}"},
        )
    ).json()["id"]

    response = await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "not_a_real_status"},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )

    assert response.status_code == 400


async def test_decide_appeal_invalid_transition_is_rejected(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grade_id = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()[0]["id"]
    appeal_id = (
        await client.post(
            f"/api/v1/academic/grades/{grade_id}/appeals",
            json={"reason": "x"},
            headers={"Authorization": f"Bearer {ctx['student_token']}"},
        )
    ).json()["id"]
    await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "rejected"},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )

    response = await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "accepted", "corrected_score": 90},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )

    assert response.status_code == 409


async def test_accept_appeal_without_corrected_score_is_rejected(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grade_id = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()[0]["id"]
    appeal_id = (
        await client.post(
            f"/api/v1/academic/grades/{grade_id}/appeals",
            json={"reason": "x"},
            headers={"Authorization": f"Bearer {ctx['student_token']}"},
        )
    ).json()["id"]

    response = await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "accepted"},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )

    assert response.status_code == 400


async def test_accept_appeal_with_out_of_range_corrected_score_is_rejected(client) -> None:
    ctx = await _seed_offering_with_grade(client)
    await client.post(
        f"/api/v1/academic/assessments/{ctx['assessment_id']}/publish",
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )
    grade_id = (
        await client.get(
            f"/api/v1/academic/assessments/{ctx['assessment_id']}/grades",
            headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
        )
    ).json()[0]["id"]
    appeal_id = (
        await client.post(
            f"/api/v1/academic/grades/{grade_id}/appeals",
            json={"reason": "x"},
            headers={"Authorization": f"Bearer {ctx['student_token']}"},
        )
    ).json()["id"]

    response = await client.post(
        f"/api/v1/academic/appeals/{appeal_id}/decision",
        json={"status": "accepted", "corrected_score": 999},
        headers={"Authorization": f"Bearer {ctx['instructor_token']}"},
    )

    assert response.status_code == 400
