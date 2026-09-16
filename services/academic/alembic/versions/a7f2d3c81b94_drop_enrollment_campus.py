"""drop enrollment campus

Campus was never a requirement and nothing consumed it - the enrollment
accepted event no longer carries campus_id either.

Revision ID: a7f2d3c81b94
Revises: ff93b50d88c7
Create Date: 2026-09-16 15:22:10.884301
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a7f2d3c81b94'
down_revision: str | None = 'ff93b50d88c7'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column('enrollments', 'campus_id')


def downgrade() -> None:
    # The original values are gone, so existing rows get a zero UUID rather
    # than the column silently failing its NOT NULL constraint.
    op.add_column(
        'enrollments',
        sa.Column(
            'campus_id',
            sa.UUID(),
            nullable=False,
            server_default=sa.text("'00000000-0000-0000-0000-000000000000'::uuid"),
        ),
    )
    op.alter_column('enrollments', 'campus_id', server_default=None)
