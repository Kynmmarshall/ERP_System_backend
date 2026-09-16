"""Dev-only cleanup of accounts and tenants left behind by the test suites.

The pytest suites create real rows in the dev database and never tear them
down, so Settings > User access slowly fills with fixture accounts. This
removes them.

    # show what would go, change nothing (default):
    docker compose exec identity python -m scripts.cleanup_test_data

    # actually delete:
    docker compose exec identity python -m scripts.cleanup_test_data --apply

Deleting an Institution cascades to its users, refresh sessions, MFA
challenges and role requests, so whole test tenants go in one step.

Safety: PROTECTED_EMAILS and PROTECTED_SLUGS are checked before any pattern,
so the seeded demo accounts and the two real institutions can never be
removed even if a pattern is later written too loosely.
"""
import argparse
import asyncio
import re

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.identity import Institution, User

# ict-main is the real tenant; dev-isolation-test is seeded on purpose as
# tenant-isolation evidence and is expected to hold zero users.
PROTECTED_SLUGS = frozenset({"ict-main", "dev-isolation-test"})

PROTECTED_EMAILS = frozenset(
    {
        "superadmin@ictuniversity.example",
        "admin@ictuniversity.example",
        "staff@ictuniversity.example",
        "student@ictuniversity.example",
        "kynmmarshall@gmail.com",
        "ngwa.bertrand@example.com",
    }
)

# Anchored, and each requires the random hex suffix the fixtures append, so a
# hand-made account like "test-account@example.com" is not swept up.
INSTITUTION_SLUG_PATTERNS = (
    re.compile(r"^test-[0-9a-f]{6,}$"),
    re.compile(r"^register-test-[0-9a-f]{6,}$"),
    re.compile(r"^rbac-[0-9a-f]{6,}$"),
    re.compile(r"^rolereq-[0-9a-f]{6,}$"),
)

USER_EMAIL_PATTERNS = (
    re.compile(r"^user-[0-9a-f]{6,}@example\.com$"),
    re.compile(r"^new-student-[0-9a-f]{6,}@example\.com$"),
    re.compile(r"^no-campus-[0-9a-f]{6,}@example\.com$"),
    re.compile(r"^sneaky-[0-9a-f]{6,}@example\.com$"),
    re.compile(r"^applicant-[0-9a-f]{6,}@example\.com$"),
    re.compile(r"^self-approve-[0-9a-f]{6,}@example\.com$"),
    re.compile(r"^(?:admin|staff|student|super_admin)-[0-9a-f]{6,}@example\.com$"),
    re.compile(r"^(?:platform-grab|orphan|shortpw|duplicate)@example\.com$"),
    re.compile(r"^livetest-[0-9a-f]{6,}@ictuniversity\.example$"),
    re.compile(r"^campustest-[0-9a-f]{6,}@ictuniversity\.example$"),
    re.compile(r"^mfatest-[0-9a-f]{6,}@ictuniversity\.example$"),
)


def is_test_institution(slug: str) -> bool:
    if slug in PROTECTED_SLUGS:
        return False
    return any(pattern.match(slug) for pattern in INSTITUTION_SLUG_PATTERNS)


def is_test_user(email: str) -> bool:
    if email in PROTECTED_EMAILS:
        return False
    return any(pattern.match(email) for pattern in USER_EMAIL_PATTERNS)


async def main(apply: bool) -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)

        institutions = (await session.execute(select(Institution))).scalars().all()
        doomed_institutions = [i for i in institutions if is_test_institution(i.slug)]
        doomed_institution_ids = {i.id for i in doomed_institutions}

        users = (await session.execute(select(User))).scalars().all()
        # Users inside a doomed tenant disappear via cascade; listing them
        # separately would double-count them in the summary.
        doomed_users = [
            u
            for u in users
            if u.institution_id not in doomed_institution_ids and is_test_user(u.email)
        ]

        cascaded = sum(1 for u in users if u.institution_id in doomed_institution_ids)

        print(f"Institutions: {len(institutions)} total, {len(doomed_institutions)} are test tenants")
        for institution in sorted(doomed_institutions, key=lambda i: i.slug)[:10]:
            print(f"    {institution.slug}")
        if len(doomed_institutions) > 10:
            print(f"    ... and {len(doomed_institutions) - 10} more")

        print(f"Users: {len(users)} total")
        print(f"    {cascaded} removed with their test tenant")
        print(f"    {len(doomed_users)} fixture accounts inside a kept tenant")
        for user in sorted(doomed_users, key=lambda u: u.email)[:10]:
            print(f"        {user.email}")
        if len(doomed_users) > 10:
            print(f"        ... and {len(doomed_users) - 10} more")

        survivors = len(users) - cascaded - len(doomed_users)
        print(f"    {survivors} accounts kept")

        if not apply:
            print("\nDry run - nothing was deleted. Re-run with --apply to remove them.")
            return

        for user in doomed_users:
            await session.delete(user)
        for institution in doomed_institutions:
            await session.delete(institution)
        await session.commit()

        print(f"\nDeleted {len(doomed_institutions)} test tenants and "
              f"{cascaded + len(doomed_users)} accounts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually delete; omit to preview only"
    )
    asyncio.run(main(parser.parse_args().apply))
