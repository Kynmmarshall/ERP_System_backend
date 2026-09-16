"""Self-registration role requests.

The whole point of this feature is that asking for a role grants nothing, so
most of these tests are about what a request does *not* do.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.security import hash_mfa_code, hash_password
from app.core.tenant_context import set_platform_context
from app.main import app
from app.models.identity import (
    Institution,
    MfaChallenge,
    Role,
    RoleRequest,
    RoleRequestStatus,
    User,
)

_PASSWORD = "correct horse battery staple"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _registration_institution(monkeypatch) -> Institution:
    unique = uuid.uuid4().hex[:10]
    async with SessionFactory() as session:
        await set_platform_context(session)
        institution = Institution(name=f"RoleReq {unique}", slug=f"rolereq-{unique}")
        session.add(institution)
        await session.commit()
        monkeypatch.setattr(settings, "self_registration_institution_slug", institution.slug)
        return institution


async def _admin_for(institution: Institution) -> User:
    unique = uuid.uuid4().hex[:10]
    async with SessionFactory() as session:
        await set_platform_context(session)
        admin = User(
            institution_id=institution.id,
            email=f"admin-{unique}@example.com",
            full_name="Reviewing Admin",
            role=Role.ADMIN,
            password_hash=hash_password(_PASSWORD),
        )
        session.add(admin)
        await session.commit()
        # commit() ended the transaction the SET LOCAL context lived in, so
        # the refresh below would be blocked by RLS without re-applying it.
        await set_platform_context(session)
        await session.refresh(admin)
        return admin


async def _admin_token(client: AsyncClient, admin: User) -> str:
    login = await client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": _PASSWORD}
    )
    challenge_id = login.json()["challenge_id"]
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(MfaChallenge).where(MfaChallenge.id == uuid.UUID(challenge_id))
        )
        challenge = result.scalar_one()
        challenge.code_hash = hash_mfa_code("123456")
        await session.commit()
    verify = await client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_id": challenge_id, "code": "123456"}
    )
    return verify.json()["access_token"]


async def _register(client: AsyncClient, **extra) -> str:
    unique = uuid.uuid4().hex[:10]
    email = f"applicant-{unique}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "a-strong-password",
            "full_name": "Role Applicant",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return email


async def test_requesting_admin_still_creates_a_student_account(client, monkeypatch) -> None:
    await _registration_institution(monkeypatch)

    email = await _register(client, requested_role="admin", justification="I run the registry")

    async with SessionFactory() as session:
        await set_platform_context(session)
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.role == Role.STUDENT

        request = (
            await session.execute(select(RoleRequest).where(RoleRequest.user_id == user.id))
        ).scalar_one()
        assert request.requested_role == Role.ADMIN
        assert request.status == RoleRequestStatus.PENDING


async def test_requesting_an_unknown_role_is_rejected(client, monkeypatch) -> None:
    await _registration_institution(monkeypatch)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "platform-grab@example.com",
            "password": "a-strong-password",
            "full_name": "Platform Grab",
            "requested_role": "super_admin",
        },
    )

    assert response.status_code == 422


async def test_registering_as_student_raises_no_request(client, monkeypatch) -> None:
    await _registration_institution(monkeypatch)

    email = await _register(client, requested_role="student")

    async with SessionFactory() as session:
        await set_platform_context(session)
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        result = await session.execute(select(RoleRequest).where(RoleRequest.user_id == user.id))
        assert result.scalar_one_or_none() is None


async def test_approving_a_request_elevates_the_user(client, monkeypatch) -> None:
    institution = await _registration_institution(monkeypatch)
    admin = await _admin_for(institution)
    email = await _register(client, requested_role="lecturer")
    token = await _admin_token(client, admin)

    listed = await client.get(
        "/api/v1/auth/role-requests", headers={"Authorization": f"Bearer {token}"}
    )
    assert listed.status_code == 200
    request_id = listed.json()[0]["id"]

    decision = await client.post(
        f"/api/v1/auth/role-requests/{request_id}/decision",
        json={"approve": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    async with SessionFactory() as session:
        await set_platform_context(session)
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.role == Role.LECTURER


async def test_rejecting_a_request_leaves_the_user_a_student(client, monkeypatch) -> None:
    institution = await _registration_institution(monkeypatch)
    admin = await _admin_for(institution)
    email = await _register(client, requested_role="admin")
    token = await _admin_token(client, admin)
    request_id = (
        await client.get("/api/v1/auth/role-requests", headers={"Authorization": f"Bearer {token}"})
    ).json()[0]["id"]

    decision = await client.post(
        f"/api/v1/auth/role-requests/{request_id}/decision",
        json={"approve": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert decision.status_code == 200
    assert decision.json()["status"] == "rejected"
    async with SessionFactory() as session:
        await set_platform_context(session)
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.role == Role.STUDENT


async def test_a_decided_request_cannot_be_decided_again(client, monkeypatch) -> None:
    institution = await _registration_institution(monkeypatch)
    admin = await _admin_for(institution)
    await _register(client, requested_role="lecturer")
    token = await _admin_token(client, admin)
    headers = {"Authorization": f"Bearer {token}"}
    request_id = (await client.get("/api/v1/auth/role-requests", headers=headers)).json()[0]["id"]
    await client.post(
        f"/api/v1/auth/role-requests/{request_id}/decision", json={"approve": True}, headers=headers
    )

    again = await client.post(
        f"/api/v1/auth/role-requests/{request_id}/decision",
        json={"approve": False},
        headers=headers,
    )

    assert again.status_code == 409


async def test_applicant_cannot_list_or_approve_their_own_request(client, monkeypatch) -> None:
    institution = await _registration_institution(monkeypatch)
    admin = await _admin_for(institution)
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"self-approve-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-strong-password",
            "full_name": "Self Approver",
            "requested_role": "admin",
        },
    )
    applicant_token = register.json()["access_token"]
    admin_token = await _admin_token(client, admin)
    request_id = (
        await client.get(
            "/api/v1/auth/role-requests", headers={"Authorization": f"Bearer {admin_token}"}
        )
    ).json()[0]["id"]

    # Still a student, so the queue is closed to them entirely.
    listed = await client.get(
        "/api/v1/auth/role-requests", headers={"Authorization": f"Bearer {applicant_token}"}
    )
    decided = await client.post(
        f"/api/v1/auth/role-requests/{request_id}/decision",
        json={"approve": True},
        headers={"Authorization": f"Bearer {applicant_token}"},
    )

    assert listed.status_code == 403
    assert decided.status_code == 403


async def test_admin_cannot_see_another_institutions_requests(client, monkeypatch) -> None:
    institution = await _registration_institution(monkeypatch)
    await _register(client, requested_role="admin")
    outsider_institution = await _registration_institution(monkeypatch)
    outsider_admin = await _admin_for(outsider_institution)
    token = await _admin_token(client, outsider_admin)

    listed = await client.get(
        "/api/v1/auth/role-requests", headers={"Authorization": f"Bearer {token}"}
    )

    assert listed.status_code == 200
    assert all(item["requested_role"] != "admin" for item in listed.json()) or listed.json() == []
    async with SessionFactory() as session:
        await set_platform_context(session)
        owned = await session.execute(
            select(RoleRequest).where(RoleRequest.institution_id == institution.id)
        )
        assert owned.scalars().first() is not None
