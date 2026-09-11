"""Idempotent dev-only seed data: one FeeSchedule matching academic's seeded
Program+Term. NOT run automatically by docker-compose or Jenkins - run
manually (after academic's seed has run):

    docker compose exec finance python -m scripts.seed

IDs must match services/identity/scripts/seed.py and
services/academic/scripts/seed.py (duplicated literal constants, not shared
code).
"""
import asyncio
import uuid

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.finance import FeeSchedule

ICT_MAIN_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SEN_PROGRAM_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
TERM_2026_S1_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
TUITION_XAF = 450_000


async def main() -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)

        existing = await session.execute(
            select(FeeSchedule).where(
                FeeSchedule.institution_id == ICT_MAIN_INSTITUTION_ID,
                FeeSchedule.program_id == SEN_PROGRAM_ID,
                FeeSchedule.term_id == TERM_2026_S1_ID,
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(
                FeeSchedule(
                    institution_id=ICT_MAIN_INSTITUTION_ID,
                    program_id=SEN_PROGRAM_ID,
                    term_id=TERM_2026_S1_ID,
                    amount_xaf=TUITION_XAF,
                )
            )
            print(f"Created fee schedule: {TUITION_XAF} XAF for program={SEN_PROGRAM_ID} term={TERM_2026_S1_ID}")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
