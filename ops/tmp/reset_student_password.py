import asyncio

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.security import hash_password
from app.core.tenant_context import set_platform_context
from app.models.identity import User


async def main() -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(User).where(User.email == "student@ictuniversity.example"))
        user = result.scalar_one()
        user.password_hash = hash_password("devPhase3Pass!23")
        user.failed_login_attempts = 0
        user.locked_until = None
        await session.commit()
        print("reset ok", user.id, user.institution_id, user.campus_id)


asyncio.run(main())
