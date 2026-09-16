"""Idempotent dev-only seed data: ICT University plus a synthetic second
institution (for tenant-isolation evidence) and one user per role. NOT run
automatically by docker-compose or Jenkins - run manually:

    docker compose exec identity python -m scripts.seed

Passwords are printed once to stdout; they are dev-only and never reused.

Institution IDs are fixed (not random) so academic/finance's own seed
scripts can reference the same institution/program/term without a cross-
service DB query - duplicated literal constants, never shared code. Keep
these in sync with services/academic/scripts/seed.py and
services/finance/scripts/seed.py if changed.
"""
import asyncio
import secrets
import uuid

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.security import hash_password
from app.core.tenant_context import set_platform_context
from app.models.identity import Institution, Role, User

ICT_MAIN_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
ISOLATION_TEST_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")

INSTITUTIONS = [
    (ICT_MAIN_INSTITUTION_ID, "ict-main", "ICT University"),
    (ISOLATION_TEST_INSTITUTION_ID, "dev-isolation-test", "Isolation Test Co."),
]

SEED_USERS = [
    ("superadmin@ictuniversity.example", "Platform Super Admin", Role.SUPER_ADMIN, None),
    ("admin@ictuniversity.example", "ICT University Admin", Role.ADMIN, "ict-main"),
    ("staff@ictuniversity.example", "ICT University Staff", Role.STAFF, "ict-main"),
    ("student@ictuniversity.example", "ICT University Student", Role.STUDENT, "ict-main"),
]


async def main() -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)

        institutions: dict[str, Institution] = {}
        for institution_id, slug, name in INSTITUTIONS:
            existing = await session.execute(select(Institution).where(Institution.id == institution_id))
            institution = existing.scalar_one_or_none()
            if institution is None:
                institution = Institution(id=institution_id, name=name, slug=slug)
                session.add(institution)
                await session.flush()
            institutions[slug] = institution

        print("Seeded credentials (dev only):")
        for email, full_name, role, institution_slug in SEED_USERS:
            existing_user = await session.execute(select(User).where(User.email == email))
            if existing_user.scalar_one_or_none() is not None:
                continue
            password = secrets.token_urlsafe(12)
            institution = institutions[institution_slug] if institution_slug else None
            session.add(
                User(
                    institution_id=institution.id if institution else None,
                    email=email,
                    full_name=full_name,
                    role=role,
                    password_hash=hash_password(password),
                )
            )
            print(f"  {email} / {password} ({role.value})")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
