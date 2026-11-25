"""add idx_peaks_name

Revision ID: c1a2b3d4e5f6
Revises: b90b920dc145
Create Date: 2026-03-21 10:00:00.000000

"""

from alembic import op
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "b90b920dc145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_peaks_name", "peaks", ["name"])


def downgrade() -> None:
    op.drop_index("idx_peaks_name", table_name="peaks")
