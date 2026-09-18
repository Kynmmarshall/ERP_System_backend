"""Admin user management - the only way roles are granted or revoked at
runtime (self-registration is student-only, see routers/auth.py).

Every route here is admin-only AND tenant-scoped: an institution admin
operates strictly inside their own institution, enforced by RLS
(set_tenant_context) on top of the explicit role check, not by either alone.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.tenant_context import set_tenant_context
from app.deps import require_roles
from app.models.identity import Role, User
from app.schemas import UserRoleUpdateRequest, UserSummaryResponse

router = APIRouter()
logger = logging.getLogger("identity.users")

_ADMIN_ROLES = (Role.ADMIN.value,)


async def _scoped_session(claims: dict, session: AsyncSession) -> None:
    await set_tenant_context(
        session, institution_id=claims.get("tenant_id"), is_platform_admin=False
    )


@router.get("", response_model=list[UserSummaryResponse])
async def list_users(
    claims: dict = Depends(require_roles(*_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    await _scoped_session(claims, session)
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


@router.patch("/{user_id}/role", response_model=UserSummaryResponse)
async def update_user_role(
    user_id: uuid.UUID,
    payload: UserRoleUpdateRequest,
    claims: dict = Depends(require_roles(*_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> User:
    # No self-service role changes at all: blocks both privilege escalation
    # and an admin accidentally demoting themselves out of the last admin seat.
    if str(user_id) == claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You cannot change your own role"
        )

    await _scoped_session(claims, session)
    # RLS already restricts this SELECT to the caller's institution, so a
    # cross-tenant user_id simply is not found rather than leaking existence.
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Admin is now the only administrative role, so demoting the last one
    # would leave the institution with nobody able to grant it back.
    if user.role == Role.ADMIN and payload.role != Role.ADMIN:
        remaining = await session.scalar(
            select(func.count()).select_from(User).where(User.role == Role.ADMIN, User.id != user.id)
        )
        if not remaining:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This is the last admin; promote another account first",
            )

    previous_role = user.role
    user.role = payload.role
    await session.commit()
    logger.info(
        "Role change: user=%s %s -> %s by actor=%s", user.id, previous_role.value, payload.role.value, claims.get("sub")
    )
    return user
