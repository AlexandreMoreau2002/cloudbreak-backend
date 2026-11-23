"""add admin observability tables"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
    )
    op.create_table(
        "cron_heartbeats",
        sa.Column("job", sa.String(20), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_status", sa.String(10), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("cron_heartbeats")
    op.drop_table("admin_audit_log")
