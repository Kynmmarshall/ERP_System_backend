"""Dev-only cleanup of rows left behind by the test suites.

The pytest suites write rows under randomly generated institution_ids and
never tear them down. Everything outside the institution(s) you name is
treated as test residue.

The institution id is a REQUIRED argument and is never guessed. The seed
constant has drifted from this workspace's live volume before, and assuming
it once cost real finance data. Get the live id from identity first:

    docker compose exec postgres psql -U identity_app -d identity_db -t -A \
      -c "SET app.is_platform_admin='true'; SELECT id, slug FROM institutions;"

Then:

    # show what would go, change nothing (default):
    docker compose exec hr python -m scripts.cleanup_test_data --keep <uuid>

    # actually delete:
    docker compose exec hr python -m scripts.cleanup_test_data --keep <uuid> --apply

Pass --keep more than once to protect several institutions.

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


async def main(keep_ids: list[uuid.UUID], apply: bool) -> None:
    tenant_tables = [t for t in Base.metadata.sorted_tables if "institution_id" in t.c]
    skipped = [t.name for t in Base.metadata.sorted_tables if "institution_id" not in t.c]

    async with SessionFactory() as session:
        await set_platform_context(session)

        print(f"Keeping: {', '.join(str(i) for i in keep_ids)}\n")

        total_keep = 0
        total_drop = 0
        for table in tenant_tables:
            is_test = table.c.institution_id.notin_(keep_ids)
            keep = await session.scalar(select(func.count()).select_from(table).where(~is_test))
            drop = await session.scalar(select(func.count()).select_from(table).where(is_test))
            total_keep += keep or 0
            total_drop += drop or 0
            marker = "  <-- test rows" if drop else ""
            print(f"  {table.name:26} keep={keep:>6}  test={drop:>6}{marker}")

        print(f"  {'TOTAL':26} keep={total_keep:>6}  test={total_drop:>6}")
        if skipped:
            print(f"  (no institution_id, untouched: {', '.join(skipped)})")

        # Keeping nothing anywhere means the id is almost certainly wrong;
        # wiping the whole database is never the intent here.
        if total_keep == 0 and total_drop > 0:
            print(
                "\nREFUSING TO RUN: the institution(s) you named own zero rows, "
                "so every row here would be deleted. Check the id against identity."
            )
            return

        if not apply:
            print("\nDry run - nothing was deleted. Re-run with --apply to remove them.")
            return

        if total_drop == 0:
            print("\nNothing to delete.")
            return

        deleted = 0
        for table in reversed(tenant_tables):
            result = await session.execute(
                delete(table).where(table.c.institution_id.notin_(keep_ids))
            )
            deleted += result.rowcount or 0
        await session.commit()
        print(f"\nDeleted {deleted} test rows.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        type=uuid.UUID,
        action="append",
        required=True,
        metavar="UUID",
        help="institution id to preserve; repeat for several",
    )
    parser.add_argument(
        "--apply", action="store_true", help="actually delete; omit to preview only"
    )
    args = parser.parse_args()
    asyncio.run(main(args.keep, args.apply))
