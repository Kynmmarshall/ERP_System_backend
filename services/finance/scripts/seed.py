"""Idempotent dev-only seed data: one FeeSchedule matching academic's seeded
Program+Term. NOT run automatically by docker-compose or Jenkins - run
manually (after academic's seed has run):

    docker compose exec finance python -m scripts.seed <institution-id>

The institution id comes from identity's live data, NOT from a constant -
the old hardcoded value drifted from this workspace's volume and produced a
fee schedule no real student could be invoiced against.
"""
import asyncio
import sys
import uuid

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.finance import FeeSchedule

SEN_PROGRAM_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
FALL_2026_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
SPRING_2027_ID = uuid.UUID("00000000-0000-4000-8000-000000000012")
TERM_IDS = (FALL_2026_ID, SPRING_2027_ID)
# One semester of tuition at ICT University.
TUITION_XAF = 365_000


async def main(institution_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)

        for term_id in TERM_IDS:
            existing = await session.execute(
                select(FeeSchedule).where(
                    FeeSchedule.institution_id == institution_id,
                    FeeSchedule.program_id == SEN_PROGRAM_ID,
                    FeeSchedule.term_id == term_id,
                )
            )
            schedule = existing.scalars().first()
            if schedule is None:
                session.add(
                    FeeSchedule(
                        institution_id=institution_id,
                        program_id=SEN_PROGRAM_ID,
                        term_id=term_id,
                        amount_xaf=TUITION_XAF,
                    )
                )
                print(f"Created fee schedule: {TUITION_XAF} XAF for term={term_id}")
            elif schedule.amount_xaf != TUITION_XAF:
                print(f"Updated tuition {schedule.amount_xaf} -> {TUITION_XAF} XAF for term={term_id}")
                schedule.amount_xaf = TUITION_XAF

        await session.commit()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: python -m scripts.seed <institution-id>\n"
            "Get the institution id from identity - never assume it."
        )
    asyncio.run(main(uuid.UUID(sys.argv[1])))
