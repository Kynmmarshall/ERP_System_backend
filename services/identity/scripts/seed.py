"""Idempotent dev-only seed data: ICT University plus a synthetic second
institution (for tenant-isolation evidence), a campus each, and one user per
role. NOT run automatically by docker-compose or Jenkins - run manually:

    docker compose exec identity python -m scripts.seed

Passwords are printed once to stdout; they are dev-only and never reused.

Institution/campus IDs are fixed (not random) so academic/finance's own seed
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
from app.models.identity import Campus, Institution, Role, User

ICT_MAIN_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
ICT_MAIN_CAMPUS_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
ISOLATION_TEST_INSTITUTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")
ISOLATION_TEST_CAMPUS_ID = uuid.UUID("00000000-0000-4000-8000-000000000004")

INSTITUTIONS = [
    (ICT_MAIN_INSTITUTION_ID, ICT_MAIN_CAMPUS_ID, "ict-main", "ICT University"),
    (ISOLATION_TEST_INSTITUTION_ID, ISOLATION_TEST_CAMPUS_ID, "dev-isolation-test", "Isolation Test Co."),
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
        campus_by_institution: dict[str, Campus] = {}
        for institution_id, campus_id, slug, name in INSTITUTIONS:
            existing = await session.execute(select(Institution).where(Institution.id == institution_id))
            institution = existing.scalar_one_or_none()
            if institution is None:
                institution = Institution(id=institution_id, name=name, slug=slug)
                session.add(institution)
                await session.flush()
            institutions[slug] = institution

            existing_campus = await session.execute(select(Campus).where(Campus.id == campus_id))
            campus = existing_campus.scalar_one_or_none()
            if campus is None:
                campus = Campus(id=campus_id, institution_id=institution.id, name=f"{name} Main Campus")
                session.add(campus)
                await session.flush()
            campus_by_institution[slug] = campus

        print("Seeded credentials (dev only):")
        for email, full_name, role, institution_slug in SEED_USERS:
            existing_user = await session.execute(select(User).where(User.email == email))
            if existing_user.scalar_one_or_none() is not None:
                continue
            password = secrets.token_urlsafe(12)
            institution = institutions[institution_slug] if institution_slug else None
            campus = campus_by_institution[institution_slug] if institution_slug else None
            session.add(
                User(
                    institution_id=institution.id if institution else None,
                    campus_id=campus.id if campus else None,
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
