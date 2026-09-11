"""Idempotent dev-only seed data: ICT University plus a synthetic second
institution (for tenant-isolation evidence), a campus each, and one user per
role. NOT run automatically by docker-compose or Jenkins - run manually:

    docker compose exec identity python -m scripts.seed

Passwords are printed once to stdout; they are dev-only and never reused.
"""
import asyncio
import secrets

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.security import hash_password
from app.core.tenant_context import set_platform_context
from app.models.identity import Campus, Institution, Role, User

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
        for slug, name in [("ict-main", "ICT University"), ("dev-isolation-test", "Isolation Test Co.")]:
            existing = await session.execute(select(Institution).where(Institution.slug == slug))
            institution = existing.scalar_one_or_none()
            if institution is None:
                institution = Institution(name=name, slug=slug)
                session.add(institution)
                await session.flush()
            institutions[slug] = institution

        campus_by_institution: dict[str, Campus] = {}
        for slug, institution in institutions.items():
            existing_campus = await session.execute(
                select(Campus).where(Campus.institution_id == institution.id)
            )
            campus = existing_campus.scalars().first()
            if campus is None:
                campus = Campus(institution_id=institution.id, name=f"{institution.name} Main Campus")
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
