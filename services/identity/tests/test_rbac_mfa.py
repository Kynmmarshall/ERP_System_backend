"""RBAC + admin-MFA tests for the identity service. Require a real, migrated
Postgres reachable via DATABASE_URL (see readme.md) - these exercise the real
role checks and real RLS, not a mocked auth layer.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.security import hash_mfa_code, hash_password
from app.core.tenant_context import set_platform_context
from app.main import app
from app.models.identity import Institution, MfaChallenge, Role, User

_PASSWORD = "correct horse battery staple"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _institution_with_users(*roles: Role) -> tuple[Institution, dict[Role, User]]:
    """One fresh institution with exactly one user per requested role, so
    cross-tenant tests can't collide with seed or other tests' data."""
    unique = uuid.uuid4().hex[:10]
    async with SessionFactory() as session:
        await set_platform_context(session)
        institution = Institution(name=f"RBAC Test {unique}", slug=f"rbac-{unique}")
        session.add(institution)
        await session.flush()

        users: dict[Role, User] = {}
        for role in roles:
            user = User(
                institution_id=institution.id,
                email=f"{role.value}-{unique}@example.com",
                full_name=f"{role.value} user",
                role=role,
                password_hash=hash_password(_PASSWORD),
            )
            session.add(user)
            users[role] = user
        await session.commit()
        return institution, users


async def _login_without_mfa(client: AsyncClient, user: User) -> str:
    """Only valid for roles that do not require MFA (student/staff)."""
    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": _PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _login_with_mfa(client: AsyncClient, user: User) -> str:
    """Completes the real two-step admin login: password -> emailed code."""
    login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": _PASSWORD})
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["mfa_required"] is True
    challenge_id = body["challenge_id"]

    # The code itself only ever leaves via email, so tests re-derive a known
    # code by overwriting the stored hash rather than reading the real one.
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(MfaChallenge).where(MfaChallenge.id == uuid.UUID(challenge_id)))
        challenge = result.scalar_one()
        challenge.code_hash = hash_mfa_code("123456")
        await session.commit()

    verify = await client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_id": challenge_id, "code": "123456"}
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["access_token"]


# --- MFA -------------------------------------------------------------------


async def test_admin_login_returns_mfa_challenge_not_tokens(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN)

    response = await client.post(
        "/api/v1/auth/login", json={"email": users[Role.ADMIN].email, "password": _PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is True
    assert "challenge_id" in body
    # The half-finished login must not hand out any usable credential.
    assert "access_token" not in body
    assert "refresh_token" not in response.cookies


async def test_super_admin_login_also_requires_mfa(client) -> None:
    _, users = await _institution_with_users(Role.SUPER_ADMIN)

    response = await client.post(
        "/api/v1/auth/login", json={"email": users[Role.SUPER_ADMIN].email, "password": _PASSWORD}
    )

    assert response.json()["mfa_required"] is True


async def test_student_and_staff_login_does_not_require_mfa(client) -> None:
    _, users = await _institution_with_users(Role.STUDENT, Role.STAFF)

    for role in (Role.STUDENT, Role.STAFF):
        response = await client.post(
            "/api/v1/auth/login", json={"email": users[role].email, "password": _PASSWORD}
        )
        body = response.json()
        assert body.get("mfa_required") is False, f"{role.value} should not need MFA"
        assert "access_token" in body


async def test_mfa_verify_with_wrong_code_is_rejected_and_counts_an_attempt(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN)
    login = await client.post(
        "/api/v1/auth/login", json={"email": users[Role.ADMIN].email, "password": _PASSWORD}
    )
    challenge_id = login.json()["challenge_id"]

    response = await client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_id": challenge_id, "code": "000000"}
    )

    assert response.status_code == 401
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(MfaChallenge).where(MfaChallenge.id == uuid.UUID(challenge_id)))
        assert result.scalar_one().attempts == 1


async def test_mfa_code_is_single_use(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN)
    token = await _login_with_mfa(client, users[Role.ADMIN])
    assert token

    # Replaying the same consumed challenge must fail even with the right code.
    login_body = None
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(MfaChallenge).where(MfaChallenge.user_id == users[Role.ADMIN].id)
        )
        login_body = result.scalars().all()[-1]

    replay = await client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_id": str(login_body.id), "code": "123456"}
    )
    assert replay.status_code == 401


async def test_mfa_expired_challenge_is_rejected(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN)
    login = await client.post(
        "/api/v1/auth/login", json={"email": users[Role.ADMIN].email, "password": _PASSWORD}
    )
    challenge_id = login.json()["challenge_id"]

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(MfaChallenge).where(MfaChallenge.id == uuid.UUID(challenge_id)))
        challenge = result.scalar_one()
        challenge.code_hash = hash_mfa_code("123456")
        challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    response = await client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_id": challenge_id, "code": "123456"}
    )
    assert response.status_code == 401


async def test_mfa_rejects_after_max_attempts_even_with_correct_code(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN)
    login = await client.post(
        "/api/v1/auth/login", json={"email": users[Role.ADMIN].email, "password": _PASSWORD}
    )
    challenge_id = login.json()["challenge_id"]

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(MfaChallenge).where(MfaChallenge.id == uuid.UUID(challenge_id)))
        challenge = result.scalar_one()
        challenge.code_hash = hash_mfa_code("123456")
        challenge.attempts = settings.mfa_max_attempts
        await session.commit()

    response = await client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_id": challenge_id, "code": "123456"}
    )
    assert response.status_code == 401


async def test_mfa_verify_with_unknown_challenge_is_rejected(client) -> None:
    response = await client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_id": str(uuid.uuid4()), "code": "123456"}
    )
    assert response.status_code == 401


# --- User management RBAC --------------------------------------------------


async def test_student_cannot_list_users(client) -> None:
    _, users = await _institution_with_users(Role.STUDENT)
    token = await _login_without_mfa(client, users[Role.STUDENT])

    response = await client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


async def test_staff_cannot_list_users(client) -> None:
    _, users = await _institution_with_users(Role.STAFF)
    token = await _login_without_mfa(client, users[Role.STAFF])

    response = await client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


async def test_unauthenticated_cannot_list_users(client) -> None:
    response = await client.get("/api/v1/auth/users")
    assert response.status_code == 401


async def test_admin_lists_only_own_institution_users(client) -> None:
    _, users_a = await _institution_with_users(Role.ADMIN, Role.STUDENT)
    _, users_b = await _institution_with_users(Role.STUDENT)
    token = await _login_with_mfa(client, users_a[Role.ADMIN])

    response = await client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    emails = {row["email"] for row in response.json()}
    assert users_a[Role.STUDENT].email in emails
    assert users_b[Role.STUDENT].email not in emails


async def test_admin_can_promote_a_student_to_staff(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN, Role.STUDENT)
    token = await _login_with_mfa(client, users[Role.ADMIN])

    response = await client.patch(
        f"/api/v1/auth/users/{users[Role.STUDENT].id}/role",
        json={"role": "staff"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "staff"


async def test_student_cannot_change_anyone_role(client) -> None:
    _, users = await _institution_with_users(Role.STUDENT, Role.STAFF)
    token = await _login_without_mfa(client, users[Role.STUDENT])

    response = await client.patch(
        f"/api/v1/auth/users/{users[Role.STAFF].id}/role",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_admin_cannot_change_own_role(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN)
    admin = users[Role.ADMIN]
    token = await _login_with_mfa(client, admin)

    response = await client.patch(
        f"/api/v1/auth/users/{admin.id}/role",
        json={"role": "super_admin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_admin_cannot_grant_super_admin(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN, Role.STUDENT)
    token = await _login_with_mfa(client, users[Role.ADMIN])

    response = await client.patch(
        f"/api/v1/auth/users/{users[Role.STUDENT].id}/role",
        json={"role": "super_admin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_admin_cannot_demote_a_super_admin(client) -> None:
    _, users = await _institution_with_users(Role.ADMIN, Role.SUPER_ADMIN)
    token = await _login_with_mfa(client, users[Role.ADMIN])

    response = await client.patch(
        f"/api/v1/auth/users/{users[Role.SUPER_ADMIN].id}/role",
        json={"role": "student"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_admin_cannot_change_role_of_user_in_another_institution(client) -> None:
    _, users_a = await _institution_with_users(Role.ADMIN)
    _, users_b = await _institution_with_users(Role.STUDENT)
    token = await _login_with_mfa(client, users_a[Role.ADMIN])

    response = await client.patch(
        f"/api/v1/auth/users/{users_b[Role.STUDENT].id}/role",
        json={"role": "staff"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # RLS hides the other tenant's row entirely, so this is a 404 (no
    # existence leak), not a 403.
    assert response.status_code == 404
