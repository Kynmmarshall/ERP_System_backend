"""replace staff role with lecturer, finance staff and marketing

The single broad "staff" role gave one person the academic, finance and
marketing workspaces at once. It is replaced by three narrow roles so each
sees only its own dashboard.

Existing STAFF accounts become LECTURER: the only seeded staff account
teaches a course offering, so that is the role that keeps its data usable.

Revision ID: b93e5d1a6c07
Revises: e4b1c7a90f22
Create Date: 2026-09-16 16:02:55.417820
"""
from collections.abc import Sequence

from alembic import op

revision: str = 'b93e5d1a6c07'
down_revision: str | None = 'e4b1c7a90f22'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_NEW_VALUES = "'SUPER_ADMIN', 'ADMIN', 'LECTURER', 'FINANCE_STAFF', 'MARKETING', 'STUDENT'"
_OLD_VALUES = "'SUPER_ADMIN', 'ADMIN', 'STAFF', 'STUDENT'"


def upgrade() -> None:
    # Postgres cannot drop a label from an enum, so the type is rebuilt.
    # STAFF is mapped to LECTURER inside the cast itself - an UPDATE first
    # would fail, because the old type has no LECTURER label to assign.
    op.execute("ALTER TYPE user_role RENAME TO user_role_old")
    op.execute(f"CREATE TYPE user_role AS ENUM ({_NEW_VALUES})")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE user_role USING "
        "(CASE WHEN role::text = 'STAFF' THEN 'LECTURER' ELSE role::text END)::user_role"
    )
    op.execute(
        "ALTER TABLE role_requests ALTER COLUMN requested_role TYPE user_role USING "
        "(CASE WHEN requested_role::text = 'STAFF' THEN 'LECTURER' "
        "ELSE requested_role::text END)::user_role"
    )
    op.execute("DROP TYPE user_role_old")


def downgrade() -> None:
    # The three narrow roles all collapse back to STAFF; the distinction
    # between them is not recoverable.
    op.execute("ALTER TYPE user_role RENAME TO user_role_new")
    op.execute(f"CREATE TYPE user_role AS ENUM ({_OLD_VALUES})")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE user_role USING "
        "(CASE WHEN role::text IN ('LECTURER', 'FINANCE_STAFF', 'MARKETING') "
        "THEN 'STAFF' ELSE role::text END)::user_role"
    )
    op.execute(
        "ALTER TABLE role_requests ALTER COLUMN requested_role TYPE user_role USING "
        "(CASE WHEN requested_role::text IN ('LECTURER', 'FINANCE_STAFF', 'MARKETING') "
        "THEN 'STAFF' ELSE requested_role::text END)::user_role"
    )
    op.execute("DROP TYPE user_role_new")
