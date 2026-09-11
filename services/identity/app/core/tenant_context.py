import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_platform_context(session: AsyncSession) -> None:
    """Used only by the unauthenticated identity-resolution steps of
    login/refresh/logout, which must look up a row by credential/token across
    all tenants before any tenant context can exist. Every other endpoint
    must use set_tenant_context with the caller's real, verified claims.
    """
    await session.execute(text("SET LOCAL app.is_platform_admin = 'true'"))
    await session.execute(text("SET LOCAL app.current_institution_id = ''"))


async def set_tenant_context(session: AsyncSession, *, institution_id: str | None, is_platform_admin: bool) -> None:
    # Postgres' SET/SET LOCAL does not accept bind parameters ($1) at all, so
    # the value must be interpolated as a SQL literal. Validate strictly
    # first so this can never become an injection vector even though the
    # inputs already come from a verified JWT, not raw client text.
    validated_institution_id = ""
    if institution_id:
        validated_institution_id = str(uuid.UUID(institution_id))
    flag = "true" if is_platform_admin else "false"

    await session.execute(text(f"SET LOCAL app.is_platform_admin = '{flag}'"))
    await session.execute(
        text(f"SET LOCAL app.current_institution_id = '{validated_institution_id}'")
    )
