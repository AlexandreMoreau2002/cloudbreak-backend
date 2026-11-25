"""add region to peaks

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-03-28 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("peaks", sa.Column("region", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("peaks", "region")
