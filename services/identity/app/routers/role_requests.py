"""Admin review of self-registration role applications.

A RoleRequest never grants anything on its own - the account was created as
STUDENT at registration. Approval here is the single point where the
elevation actually happens, and it reuses the same guards as direct role
edits in routers/users.py.
"""
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.tenant_context import set_tenant_context
from app.deps import require_roles
from app.models.identity import Role, RoleRequest, RoleRequestStatus, User
from app.schemas import RoleRequestDecisionRequest, RoleRequestResponse

router = APIRouter()
logger = logging.getLogger("identity.role_requests")

_ADMIN_ROLES = (Role.ADMIN.value, Role.SUPER_ADMIN.value)


async def _scoped_session(claims: dict, session: AsyncSession) -> None:
    is_platform_admin = claims.get("role") == Role.SUPER_ADMIN.value and claims.get("tenant_id") is None
    await set_tenant_context(
        session, institution_id=claims.get("tenant_id"), is_platform_admin=is_platform_admin
    )


@router.get("", response_model=list[RoleRequestResponse])
async def list_role_requests(
    claims: dict = Depends(require_roles(*_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[RoleRequest]:
    await _scoped_session(claims, session)
    result = await session.execute(select(RoleRequest).order_by(RoleRequest.created_at.desc()))
    return list(result.scalars().all())


@router.post("/{request_id}/decision", response_model=RoleRequestResponse)
async def decide_role_request(
    request_id: uuid.UUID,
    payload: RoleRequestDecisionRequest,
    claims: dict = Depends(require_roles(*_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> RoleRequest:
    await _scoped_session(claims, session)

    # RLS scopes this to the caller's institution, so a cross-tenant id is
    # simply not found rather than leaking that it exists.
    result = await session.execute(select(RoleRequest).where(RoleRequest.id == request_id))
    role_request = result.scalar_one_or_none()
    if role_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if role_request.status != RoleRequestStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already decided")

    # Mirrors routers/users.py: nobody approves their own elevation.
    if str(role_request.user_id) == claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You cannot decide your own request"
        )

    user_result = await session.execute(select(User).where(User.id == role_request.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.approve:
        user.role = role_request.requested_role
        role_request.status = RoleRequestStatus.APPROVED
    else:
        role_request.status = RoleRequestStatus.REJECTED

    role_request.decided_by = uuid.UUID(claims["sub"])
    role_request.decided_at = datetime.now(UTC)
    await session.commit()
    logger.info(
        "Role request %s: request=%s user=%s role=%s actor=%s",
        role_request.status.value,
        role_request.id,
        user.id,
        role_request.requested_role.value,
        claims.get("sub"),
    )
    return role_request
