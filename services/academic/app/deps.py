from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decode_access_token
from app.core.tenant_context import set_tenant_context

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc


async def get_tenant_session(
    claims: dict = Depends(get_current_claims), session: AsyncSession = Depends(get_session)
) -> AsyncIterator[AsyncSession]:
    is_platform_admin = claims.get("role") == "super_admin" and claims.get("tenant_id") is None
    await set_tenant_context(session, institution_id=claims.get("tenant_id"), is_platform_admin=is_platform_admin)
    yield session


def require_roles(*allowed_roles: str) -> Callable[..., Coroutine[Any, Any, dict]]:
    async def _check(claims: dict = Depends(get_current_claims)) -> dict:
        if claims.get("role") not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return claims

    return _check
