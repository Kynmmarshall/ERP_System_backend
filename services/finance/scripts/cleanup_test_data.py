"""Dev-only cleanup of rows left behind by the test suites.

The pytest suites write real rows into the dev database under randomly
generated institution_ids and never tear them down. Anything belonging to a
tenant other than the two seeded ones is therefore test residue.

    # show what would go, change nothing (default):
    docker compose exec finance python -m scripts.cleanup_test_data

    # actually delete:
    docker compose exec finance python -m scripts.cleanup_test_data --apply

Rows are deleted child-table-first (reverse of SQLAlchemy's dependency sort)
so foreign keys never block the delete.
"""
import argparse
import asyncio
import uuid

from sqlalchemy import delete, func, select

import app.models  # noqa: F401  - registers every table on Base.metadata
from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.base import Base

# Must match services/identity/scripts/seed.py (duplicated literal, not
# shared code - the services share no Python).
KEEP_INSTITUTION_IDS = (
    uuid.UUID("00000000-0000-4000-8000-000000000001"),  # ICT University
    uuid.UUID("00000000-0000-4000-8000-000000000003"),  # Isolation Test Co.
)


async def main(apply: bool) -> None:
    tenant_tables = [t for t in Base.metadata.sorted_tables if "institution_id" in t.c]
    skipped = [t.name for t in Base.metadata.sorted_tables if "institution_id" not in t.c]

    async with SessionFactory() as session:
        await set_platform_context(session)

        total_keep = 0
        total_drop = 0
        for table in tenant_tables:
            is_test = table.c.institution_id.notin_(KEEP_INSTITUTION_IDS)
            keep = await session.scalar(
                select(func.count()).select_from(table).where(~is_test)
            )
            drop = await session.scalar(
                select(func.count()).select_from(table).where(is_test)
            )
            total_keep += keep or 0
            total_drop += drop or 0
            marker = "  <-- test rows" if drop else ""
            print(f"  {table.name:26} keep={keep:>6}  test={drop:>6}{marker}")

        print(f"  {'TOTAL':26} keep={total_keep:>6}  test={total_drop:>6}")
        if skipped:
            print(f"  (no institution_id, untouched: {', '.join(skipped)})")

        if not apply:
            print("\nDry run - nothing was deleted. Re-run with --apply to remove them.")
            return

        if total_drop == 0:
            print("\nNothing to delete.")
            return

        deleted = 0
        for table in reversed(tenant_tables):
            result = await session.execute(
                delete(table).where(table.c.institution_id.notin_(KEEP_INSTITUTION_IDS))
            )
            deleted += result.rowcount or 0
        await session.commit()
        print(f"\nDeleted {deleted} test rows.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually delete; omit to preview only"
    )
    asyncio.run(main(parser.parse_args().apply))
