"""subscription origin (apple|granted) and admin audit target columns"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="apple"),
    )
    op.add_column("admin_audit_log", sa.Column("target_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "admin_audit_log", sa.Column("target_user_id", sa.String(length=255), nullable=True)
    )
    op.add_column("admin_audit_log", sa.Column("grant_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_audit_log", "grant_days")
    op.drop_column("admin_audit_log", "target_user_id")
    op.drop_column("admin_audit_log", "target_hash")
    op.drop_column("subscriptions", "origin")
