"""Add user interface locale.

Revision ID: b7c8d9e0f1a2
Revises: a5b1c2d3e4f5
Create Date: 2026-10-12 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a5b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=5), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
