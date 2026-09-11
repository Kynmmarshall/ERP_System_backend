import asyncio
import uuid

from sqlalchemy import update

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.academic import Enrollment, OutboxEvent, Program, Term

OLD_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
ACTUAL_INSTITUTION_ID = uuid.UUID("a5994dbd-83ea-4582-9f4e-760e7753577e")


async def main() -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)
        for model in (Program, Term, Enrollment, OutboxEvent):
            result = await session.execute(
                update(model)
                .where(model.institution_id == OLD_INSTITUTION_ID)
                .values(institution_id=ACTUAL_INSTITUTION_ID)
            )
            print(model.__tablename__, result.rowcount)
        await session.commit()


asyncio.run(main())
