"""drop campus

Campus was never part of the system's requirements - one institution has one
campus, it was never an authorization boundary, and nothing read it. Dropping
it removes the users.campus_id column, the campuses table, and by extension
the campus_id JWT claim and X-Campus-Id header.

Revision ID: e4b1c7a90f22
Revises: c17d94b2f5ea
Create Date: 2026-09-16 15:20:41.552108
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'e4b1c7a90f22'
down_revision: str | None = 'c17d94b2f5ea'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column('users', 'campus_id')
    op.drop_index('ix_campuses_institution_id', table_name='campuses')
    op.drop_table('campuses')


def downgrade() -> None:
    op.create_table(
        'campuses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('institution_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_campuses_institution_id', 'campuses', ['institution_id'], unique=False)
    # The campus each user belonged to is not recoverable, so the restored
    # column comes back empty rather than guessing.
    op.add_column('users', sa.Column('campus_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'users_campus_id_fkey', 'users', 'campuses', ['campus_id'], ['id'], ondelete='SET NULL'
    )
