import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import (
    generate_refresh_token,
    hash_refresh_token,
    issue_access_token,
    refresh_token_expiry,
    verify_password,
)
from app.core.tenant_context import set_platform_context, set_tenant_context
from app.deps import get_current_claims
from app.models.identity import RefreshSession, Role, User
from app.schemas import AccessTokenResponse, LoginRequest, MeResponse

router = APIRouter()

_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.refresh_cookie_name, path=_REFRESH_COOKIE_PATH)


async def _issue_tokens_for_user(session: AsyncSession, response: Response, user: User) -> AccessTokenResponse:
    access_token = issue_access_token(
        user_id=user.id, institution_id=user.institution_id, campus_id=user.campus_id, role=user.role.value
    )
    refresh_token, token_hash = generate_refresh_token()
    session.add(
        RefreshSession(
            user_id=user.id,
            institution_id=user.institution_id,
            family_id=uuid.uuid4(),
            token_hash=token_hash,
            expires_at=refresh_token_expiry(),
        )
    )
    await session.commit()
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(
        access_token=access_token, expires_in_seconds=settings.access_token_ttl_minutes * 60
    )


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest, response: Response, session: AsyncSession = Depends(get_session)
) -> AccessTokenResponse:
    await set_platform_context(session)
    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()

    generic_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user is None or not user.is_active:
        raise generic_error

    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        # Distinct from "invalid credentials" is a deliberate, documented
        # trade-off: this project must demonstrably show account lockout
        # behavior; a public consumer product would likely keep this generic.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account temporarily locked due to repeated failed attempts",
        )

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.max_failed_login_attempts:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
        await session.commit()
        raise generic_error

    user.failed_login_attempts = 0
    user.locked_until = None
    return await _issue_tokens_for_user(session, response, user)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> AccessTokenResponse:
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh session")

    await set_platform_context(session)
    token_hash = hash_refresh_token(raw_token)
    result = await session.execute(select(RefreshSession).where(RefreshSession.token_hash == token_hash))
    stored = result.scalar_one_or_none()

    if stored is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh session")

    now = datetime.now(UTC)

    if stored.revoked_at is not None:
        # This exact token was already rotated out once before - reuse is a
        # theft signal, so the whole rotation family is revoked immediately.
        await session.execute(
            update(RefreshSession)
            .where(RefreshSession.family_id == stored.family_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked, please log in again")

    if stored.expires_at < now:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session expired")

    user_result = await session.execute(select(User).where(User.id == stored.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")

    stored.revoked_at = now
    new_refresh_token, new_hash = generate_refresh_token()
    session.add(
        RefreshSession(
            user_id=user.id,
            institution_id=user.institution_id,
            family_id=stored.family_id,
            token_hash=new_hash,
            expires_at=refresh_token_expiry(),
        )
    )
    await session.commit()

    access_token = issue_access_token(
        user_id=user.id, institution_id=user.institution_id, campus_id=user.campus_id, role=user.role.value
    )
    _set_refresh_cookie(response, new_refresh_token)
    return AccessTokenResponse(
        access_token=access_token, expires_in_seconds=settings.access_token_ttl_minutes * 60
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> None:
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        await set_platform_context(session)
        token_hash = hash_refresh_token(raw_token)
        await session.execute(
            update(RefreshSession)
            .where(RefreshSession.token_hash == token_hash, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    _clear_refresh_cookie(response)


@router.get("/me", response_model=MeResponse)
async def me(
    claims: dict = Depends(get_current_claims), session: AsyncSession = Depends(get_session)
) -> MeResponse:
    is_platform_admin = claims.get("role") == Role.SUPER_ADMIN.value and claims.get("tenant_id") is None
    await set_tenant_context(session, institution_id=claims.get("tenant_id"), is_platform_admin=is_platform_admin)
    result = await session.execute(select(User).where(User.id == uuid.UUID(claims["sub"])))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        institution_id=user.institution_id,
        campus_id=user.campus_id,
    )
