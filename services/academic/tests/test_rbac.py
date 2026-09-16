"""Role-enforcement (403) tests for academic. Deliberately assert on the
role gate ONLY - a rejected caller must never reach the business logic, so
these send minimal/empty bodies and still expect 403, never 422.
"""
import uuid

from tests.helpers import mint_token


def _auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(role=role)}"}


async def test_student_cannot_create_a_course(client) -> None:
    response = await client.post(
        "/api/v1/academic/courses",
        json={"code": "SEN101", "title": "Intro", "credits": 3},
        headers=_auth("student"),
    )
    assert response.status_code == 403


async def test_student_cannot_create_a_course_offering(client) -> None:
    response = await client.post(
        "/api/v1/academic/course-offerings",
        json={"course_id": str(uuid.uuid4()), "term_id": str(uuid.uuid4()), "instructor_id": str(uuid.uuid4())},
        headers=_auth("student"),
    )
    assert response.status_code == 403


async def test_student_cannot_add_a_prerequisite(client) -> None:
    response = await client.post(
        f"/api/v1/academic/courses/{uuid.uuid4()}/prerequisites",
        json={"prerequisite_course_id": str(uuid.uuid4())},
        headers=_auth("student"),
    )
    assert response.status_code == 403


async def test_unauthenticated_cannot_create_a_course(client) -> None:
    response = await client.post(
        "/api/v1/academic/courses", json={"code": "SEN101", "title": "Intro", "credits": 3}
    )
    assert response.status_code == 401


async def test_staff_is_allowed_past_the_role_gate_on_course_creation(client) -> None:
    """Proves the 403s above are really about ROLE, not a blanket rejection:
    the same call as staff gets past the gate and into real validation."""
    response = await client.post(
        "/api/v1/academic/courses",
        json={"code": "SEN101", "title": "Intro", "credits": 3},
        headers=_auth("staff"),
    )
    assert response.status_code != 403
