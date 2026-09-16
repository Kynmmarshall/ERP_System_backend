"""merge super admin into admin

A single institution does not need both a tenant administrator and a
platform operator. SUPER_ADMIN is merged into ADMIN, leaving five roles.

The control SUPER_ADMIN used to provide - nobody verifies the payroll
schedule they authored themselves - is preserved in the HR service as a
four-eyes check on the user id instead of a second role
(see hr/alembic c8a41f7b25d9).

Revision ID: d0c5e83a1f46
Revises: b93e5d1a6c07
Create Date: 2026-09-16 18:24:38.201774
"""
from collections.abc import Sequence

from alembic import op

revision: str = 'd0c5e83a1f46'
down_revision: str | None = 'b93e5d1a6c07'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_NEW_VALUES = "'ADMIN', 'LECTURER', 'FINANCE_STAFF', 'MARKETING', 'STUDENT'"
_OLD_VALUES = "'SUPER_ADMIN', 'ADMIN', 'LECTURER', 'FINANCE_STAFF', 'MARKETING', 'STUDENT'"


def upgrade() -> None:
    # A tenantless SUPER_ADMIN would be invisible to row-level security once
    # it becomes a plain ADMIN, so adopt the single institution first.
    op.execute(
        "UPDATE users SET institution_id = (SELECT id FROM institutions ORDER BY created_at LIMIT 1) "
        "WHERE institution_id IS NULL"
    )

    # Postgres cannot drop an enum label; the type is rebuilt and SUPER_ADMIN
    # is mapped inside the cast (an UPDATE first would fail - the old type has
    # no replacement label to assign).
    op.execute("ALTER TYPE user_role RENAME TO user_role_old")
    op.execute(f"CREATE TYPE user_role AS ENUM ({_NEW_VALUES})")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE user_role USING "
        "(CASE WHEN role::text = 'SUPER_ADMIN' THEN 'ADMIN' ELSE role::text END)::user_role"
    )
    op.execute(
        "ALTER TABLE role_requests ALTER COLUMN requested_role TYPE user_role USING "
        "(CASE WHEN requested_role::text = 'SUPER_ADMIN' THEN 'ADMIN' "
        "ELSE requested_role::text END)::user_role"
    )
    op.execute("DROP TYPE user_role_old")


def downgrade() -> None:
    # Which admins were once super admins is not recoverable; they all stay
    # ADMIN rather than guessing.
    op.execute("ALTER TYPE user_role RENAME TO user_role_new")
    op.execute(f"CREATE TYPE user_role AS ENUM ({_OLD_VALUES})")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::text::user_role")
    op.execute(
        "ALTER TABLE role_requests "
        "ALTER COLUMN requested_role TYPE user_role USING requested_role::text::user_role"
    )
    op.execute("DROP TYPE user_role_new")
