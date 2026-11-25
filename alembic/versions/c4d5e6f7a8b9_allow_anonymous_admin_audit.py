"""allow anonymous admin audit entries"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "admin_audit_log", "actor_id", existing_type=sa.String(length=255), nullable=True
    )


def downgrade() -> None:
    op.execute("UPDATE admin_audit_log SET actor_id = 'unknown' WHERE actor_id IS NULL")
    op.alter_column(
        "admin_audit_log", "actor_id", existing_type=sa.String(length=255), nullable=False
    )
