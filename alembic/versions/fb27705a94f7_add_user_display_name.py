"""Add optional user display name.

Revision ID: fb27705a94f7
Revises: e5f4a0000002
Create Date: 2026-10-08 12:09:44.408665

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fb27705a94f7"
down_revision: str | None = "e5f4a0000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=25), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
