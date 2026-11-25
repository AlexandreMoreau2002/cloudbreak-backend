"""add verified Apple paid-period watermark to subscriptions"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e5f4a0000002"
down_revision: str | None = "c8d1e5f2a7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("apple_period_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "apple_period_expires_at")
