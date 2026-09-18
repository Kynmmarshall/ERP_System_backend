"""payroll schedule four-eyes columns

Records who created a rate schedule and who verified it, so verification can
require a different person than the author. Previously the separation came
from a second ROLE (super_admin); with a single admin role it has to come
from a second PERSON.

Revision ID: c8a41f7b25d9
Revises: 5e3c398fa17b
Create Date: 2026-09-16 18:20:14.663201
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8a41f7b25d9"
down_revision: str | None = "5e3c398fa17b"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: schedules created before this migration have no recorded
    # author, and inventing one would misrepresent who approved what.
    op.add_column(
        "payroll_schedule_versions", sa.Column("created_by", sa.UUID(), nullable=True)
    )
    op.add_column(
        "payroll_schedule_versions", sa.Column("verified_by", sa.UUID(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("payroll_schedule_versions", "verified_by")
    op.drop_column("payroll_schedule_versions", "created_by")
