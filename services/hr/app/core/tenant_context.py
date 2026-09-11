import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_platform_context(session: AsyncSession) -> None:
    """Used only by dev/seed scripts and trusted background workers that
    must read/write rows across all tenants. Every request-handling
    endpoint must use set_tenant_context with the caller's real, verified
    claims instead.
    """
    await session.execute(text("SET LOCAL app.is_platform_admin = 'true'"))
    await session.execute(text("SET LOCAL app.current_institution_id = ''"))


async def set_tenant_context(session: AsyncSession, *, institution_id: str | None, is_platform_admin: bool) -> None:
    # Postgres SET/SET LOCAL does not accept bind parameters at all, so the
    # value must be interpolated as a validated SQL literal (see identity's
    # tenant_context.py for the same rationale).
    validated_institution_id = ""
    if institution_id:
        validated_institution_id = str(uuid.UUID(institution_id))
    flag = "true" if is_platform_admin else "false"

    await session.execute(text(f"SET LOCAL app.is_platform_admin = '{flag}'"))
    await session.execute(text(f"SET LOCAL app.current_institution_id = '{validated_institution_id}'"))
