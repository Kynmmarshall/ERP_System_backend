"""Auth-flow tests. Require a real, migrated Postgres reachable via
DATABASE_URL (see readme.md "Database isolation check" / CI for how to bring
one up) - these deliberately exercise real RLS, not a mocked DB layer.
"""
import uuid

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.security import hash_password, issue_access_token
from app.core.tenant_context import set_platform_context
from app.main import app
from app.models.identity import Campus, Institution, Role, User


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_user(
    *, role: Role = Role.STUDENT, password: str = "correct horse battery staple"
) -> tuple[User, Institution]:
    unique = uuid.uuid4().hex[:10]
    async with SessionFactory() as session:
        await set_platform_context(session)
        institution = Institution(name=f"Test Institution {unique}", slug=f"test-{unique}")
        session.add(institution)
        await session.flush()
        campus = Campus(institution_id=institution.id, name="Main")
        session.add(campus)
        await session.flush()
        user = User(
            institution_id=institution.id,
            campus_id=campus.id,
            email=f"user-{unique}@example.com",
            full_name="Test User",
            role=role,
            password_hash=hash_password(password),
        )
        session.add(user)
        await session.commit()
        return user, institution


async def test_login_with_valid_credentials_returns_access_token_and_refresh_cookie(client) -> None:
    user, _ = await _create_user(password="correct horse battery staple")

    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "correct horse battery staple"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert "refresh_token" in response.cookies


async def test_login_with_wrong_password_is_rejected(client) -> None:
    user, _ = await _create_user(password="correct horse battery staple")

    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong"})

    assert response.status_code == 401


async def test_login_with_unknown_email_is_rejected(client) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )

    assert response.status_code == 401


async def test_refresh_without_cookie_is_rejected(client) -> None:
    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401


async def test_account_locks_after_repeated_failed_attempts(client) -> None:
    user, _ = await _create_user(password="correct horse battery staple")

    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong"})

    locked_response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "correct horse battery staple"}
    )

    assert locked_response.status_code == 401
    assert "locked" in locked_response.json()["detail"].lower()


async def test_me_returns_profile_scoped_to_own_tenant(client) -> None:
    user, institution = await _create_user(role=Role.ADMIN, password="correct horse battery staple")
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "correct horse battery staple"}
    )
    access_token = login_response.json()["access_token"]

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["institution_id"] == str(institution.id)
    assert body["role"] == "admin"


async def test_me_rejects_tampered_token(client) -> None:
    user, _ = await _create_user()
    token = issue_access_token(
        user_id=user.id, institution_id=user.institution_id, campus_id=user.campus_id, role=user.role.value
    )
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"})

    assert response.status_code == 401


async def test_me_rejects_expired_token(client) -> None:
    user, _ = await _create_user()
    # Force an already-expired token to prove expiry is actually enforced.
    from datetime import UTC, datetime, timedelta

    from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER, _load_private_key

    now = datetime.now(UTC)
    expired_token = jwt.encode(
        {
            "sub": str(user.id),
            "tenant_id": str(user.institution_id),
            "campus_id": None,
            "role": user.role.value,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "iat": now - timedelta(minutes=20),
            "exp": now - timedelta(minutes=10),
            "jti": str(uuid.uuid4()),
        },
        _load_private_key(),
        algorithm=JWT_ALGORITHM,
    )

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})

    assert response.status_code == 401


async def test_refresh_rotates_token_and_reuse_revokes_family(client) -> None:
    user, _ = await _create_user(password="correct horse battery staple")
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "correct horse battery staple"}
    )
    old_refresh_cookie = login_response.cookies["refresh_token"]

    refresh_response = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_cookie}
    )
    assert refresh_response.status_code == 200
    new_refresh_cookie = refresh_response.cookies["refresh_token"]
    assert new_refresh_cookie != old_refresh_cookie

    # Reusing the now-rotated-out old token must be rejected...
    reuse_response = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_cookie}
    )
    assert reuse_response.status_code == 401

    # ...and must have revoked the whole family, including the new token.
    second_use_of_new_token = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": new_refresh_cookie}
    )
    assert second_use_of_new_token.status_code == 401


async def test_logout_revokes_refresh_session(client) -> None:
    user, _ = await _create_user(password="correct horse battery staple")
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "correct horse battery staple"}
    )
    refresh_cookie = login_response.cookies["refresh_token"]

    logout_response = await client.post("/api/v1/auth/logout", cookies={"refresh_token": refresh_cookie})
    assert logout_response.status_code == 204

    refresh_after_logout = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": refresh_cookie}
    )
    assert refresh_after_logout.status_code == 401


async def test_internal_verify_sets_headers_for_gateway_auth_request(client) -> None:
    user, institution = await _create_user(role=Role.STAFF, password="correct horse battery staple")
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "correct horse battery staple"}
    )
    access_token = login_response.json()["access_token"]

    response = await client.get("/internal/verify", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.headers["X-User-Id"] == str(user.id)
    assert response.headers["X-Tenant-Id"] == str(institution.id)
    assert response.headers["X-Roles"] == "staff"


async def test_internal_verify_rejects_missing_token(client) -> None:
    response = await client.get("/internal/verify")
    assert response.status_code == 401


async def test_users_from_different_institutions_are_isolated_by_rls() -> None:
    user_a, institution_a = await _create_user()
    user_b, institution_b = await _create_user()

    async with SessionFactory() as session:
        from app.core.tenant_context import set_tenant_context

        await set_tenant_context(session, institution_id=str(institution_a.id), is_platform_admin=False)
        result = await session.execute(select(User).where(User.id == user_b.id))
        assert result.scalar_one_or_none() is None

        result_own = await session.execute(select(User).where(User.id == user_a.id))
        assert result_own.scalar_one_or_none() is not None
