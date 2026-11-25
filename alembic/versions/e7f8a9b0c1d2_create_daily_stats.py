"""create daily_stats snapshots"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_stats",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("users_total", sa.Integer(), nullable=False),
        sa.Column("accounts_total", sa.Integer(), nullable=False),
        sa.Column("checks", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_stats")
