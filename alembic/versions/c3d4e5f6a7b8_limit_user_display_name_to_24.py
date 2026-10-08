"""Limit optional user display name to 24 characters.

Revision ID: c3d4e5f6a7b8
Revises: fb27705a94f7
"""

from alembic import op
import sqlalchemy as sa
from collections.abc import Sequence

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "fb27705a94f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "display_name",
        existing_type=sa.String(length=25),
        type_=sa.String(length=24),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "display_name",
        existing_type=sa.String(length=24),
        type_=sa.String(length=25),
        existing_nullable=True,
    )
