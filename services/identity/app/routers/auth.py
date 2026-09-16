import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.mfa_email import send_mfa_code
from app.core.security import (
    generate_mfa_code,
    generate_refresh_token,
    hash_mfa_code,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    mfa_challenge_expiry,
    refresh_token_expiry,
    verify_password,
)
from app.core.tenant_context import set_platform_context, set_tenant_context
from app.deps import get_current_claims
from app.models.identity import Campus, Institution, MfaChallenge, RefreshSession, Role, User
from app.schemas import (
    AccessTokenResponse,
    LoginRequest,
    MeResponse,
    MfaChallengeResponse,
    MfaVerifyRequest,
    RegisterRequest,
)

router = APIRouter()
logger = logging.getLogger("identity.auth")

_REFRESH_COOKIE_PATH = "/api/v1/auth"

# MFA is mandatory for every elevated account - these roles can change other
# users' roles and approve payroll, so a stolen password alone must not be
# enough. Students/staff are deliberately excluded: forcing an email round
# trip on every student login is not justified by their privilege level.
MFA_REQUIRED_ROLES = (Role.ADMIN, Role.SUPER_ADMIN)


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


@router.post("/login", response_model=AccessTokenResponse | MfaChallengeResponse)
async def login(
    payload: LoginRequest, response: Response, session: AsyncSession = Depends(get_session)
) -> AccessTokenResponse | MfaChallengeResponse:
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

    if user.role in MFA_REQUIRED_ROLES:
        return await _start_mfa_challenge(session, user)

    return await _issue_tokens_for_user(session, response, user)


async def _start_mfa_challenge(session: AsyncSession, user: User) -> MfaChallengeResponse:
    code, code_hash = generate_mfa_code()
    challenge = MfaChallenge(
        user_id=user.id,
        institution_id=user.institution_id,
        code_hash=code_hash,
        expires_at=mfa_challenge_expiry(),
    )
    session.add(challenge)
    await session.commit()

    # Delivery failure must not hand out a usable session, and must not leak
    # the code into the response either - fail the login instead.
    try:
        await send_mfa_code(to_email=user.email, to_name=user.full_name, code=code)
    except Exception as exc:
        logger.exception("Failed to deliver MFA code for user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not send your sign-in code, please try again",
        ) from exc

    return MfaChallengeResponse(
        challenge_id=challenge.id, expires_in_seconds=settings.mfa_otp_ttl_minutes * 60
    )


@router.post("/mfa/verify", response_model=AccessTokenResponse)
async def verify_mfa(
    payload: MfaVerifyRequest, response: Response, session: AsyncSession = Depends(get_session)
) -> AccessTokenResponse:
    """Second factor for admin/super_admin logins. Deliberately returns one
    generic error for every failure mode (unknown/expired/consumed/wrong
    code) so it cannot be used to probe which challenge ids exist.
    """
    await set_platform_context(session)
    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code"
    )

    result = await session.execute(
        select(MfaChallenge).where(MfaChallenge.id == payload.challenge_id).with_for_update()
    )
    challenge = result.scalar_one_or_none()
    if challenge is None or challenge.consumed_at is not None:
        raise generic_error

    now = datetime.now(UTC)
    if challenge.expires_at < now or challenge.attempts >= settings.mfa_max_attempts:
        raise generic_error

    if not secrets.compare_digest(challenge.code_hash, hash_mfa_code(payload.code)):
        challenge.attempts += 1
        await session.commit()
        raise generic_error

    challenge.consumed_at = now
    user_result = await session.execute(select(User).where(User.id == challenge.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        await session.commit()
        raise generic_error
    await session.commit()

    # commit() ended the transaction holding the SET LOCAL context.
    await set_platform_context(session)
    return await _issue_tokens_for_user(session, response, user)


@router.post("/register", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, response: Response, session: AsyncSession = Depends(get_session)
) -> AccessTokenResponse:
    """Public self-registration. Always creates a STUDENT account in the
    configured institution - role/institution are never accepted from the
    client, only ever derived server-side. Staff/admin accounts remain
    admin-provisioned only (see readme.md / scripts/seed.py).
    """
    await set_platform_context(session)
    email = payload.email.lower()
    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    institution_result = await session.execute(
        select(Institution).where(Institution.slug == settings.self_registration_institution_slug)
    )
    institution = institution_result.scalar_one_or_none()
    if institution is None:
        # Misconfiguration (bad slug), not a client error - never silently
        # register a student under no institution at all.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Registration is not available right now"
        )

    # Looked up from real data rather than a hardcoded seed UUID, which has
    # drifted from this workspace's live volume before (see repo notes).
    # Stays null if the institution has no campus yet - a missing campus is
    # an admin task, not a reason to block account creation.
    campus_result = await session.execute(
        select(Campus)
        .where(Campus.institution_id == institution.id)
        .order_by(Campus.created_at, Campus.id)
        .limit(1)
    )
    campus = campus_result.scalar_one_or_none()

    user = User(
        institution_id=institution.id,
        campus_id=campus.id if campus else None,
        email=email,
        full_name=payload.full_name,
        role=Role.STUDENT,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists"
        ) from exc

    # commit() ends the transaction the SET LOCAL context above lived in -
    # must be re-applied before _issue_tokens_for_user's own insert below,
    # or RLS silently blocks it (see app/core/tenant_context.py).
    await set_platform_context(session)
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
