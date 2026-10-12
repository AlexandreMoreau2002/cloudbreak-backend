"""Add user push token and validity flag.

Revision ID: a5b1c2d3e4f5
Revises: fb27705a94f7
Create Date: 2026-10-09 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "a5b1c2d3e4f5"
down_revision: str | None = "fb27705a94f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("push_token", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("push_token_valid", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_users_push_token",
        "users",
        ["push_token"],
        unique=True,
        postgresql_where=sa.text("push_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_push_token", table_name="users")
    op.drop_column("users", "push_token_valid")
    op.drop_column("users", "push_token")
