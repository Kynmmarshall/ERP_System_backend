"""role requests

Revision ID: c17d94b2f5ea
Revises: aab86425d318
Create Date: 2026-09-16 14:40:02.118433
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'c17d94b2f5ea'
down_revision: str | None = 'aab86425d318'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    role_request_status = postgresql.ENUM(
        'PENDING', 'APPROVED', 'REJECTED', name='role_request_status'
    )
    role_request_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'role_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('institution_id', sa.UUID(), nullable=True),
        # Reuses the existing user_role enum rather than defining a parallel
        # one, so a requested role can never drift from a grantable role.
        sa.Column(
            'requested_role',
            postgresql.ENUM(
                'SUPER_ADMIN', 'ADMIN', 'STAFF', 'STUDENT', name='user_role', create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            'status',
            postgresql.ENUM(
                'PENDING', 'APPROVED', 'REJECTED', name='role_request_status', create_type=False
            ),
            nullable=False,
        ),
        sa.Column('justification', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_role_requests_institution_id', 'role_requests', ['institution_id'], unique=False
    )
    op.create_index(
        'uq_role_requests_one_pending_per_user',
        'role_requests',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    # Autogenerate never emits RLS - mirror the tenant-isolation policy the
    # other identity tables carry, or this becomes a cross-tenant hole.
    op.execute("ALTER TABLE role_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON role_requests
        USING (
            current_setting('app.is_platform_admin', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
        )
        WITH CHECK (
            current_setting('app.is_platform_admin', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON role_requests")
    op.drop_index('uq_role_requests_one_pending_per_user', table_name='role_requests')
    op.drop_index('ix_role_requests_institution_id', table_name='role_requests')
    op.drop_table('role_requests')
    postgresql.ENUM(name='role_request_status').drop(op.get_bind(), checkfirst=True)
