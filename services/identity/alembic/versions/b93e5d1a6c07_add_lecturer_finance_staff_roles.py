"""add lecturer and finance staff roles

Splits the broad "staff" role into two narrower ones. STAFF is kept so
existing accounts keep working; new accounts should get LECTURER or
FINANCE_STAFF instead.

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


def upgrade() -> None:
    # Postgres 12+ allows ADD VALUE inside a transaction; the new labels just
    # cannot be referenced until this migration commits.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'LECTURER'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'FINANCE_STAFF'")


def downgrade() -> None:
    # Postgres cannot drop a single enum label. Reversing would mean
    # recreating user_role without these two values and rewriting every
    # column that uses it, which would silently destroy any account already
    # holding one - so this is deliberately not automated.
    raise NotImplementedError(
        "Dropping an enum label is not supported; reassign affected users first."
    )
