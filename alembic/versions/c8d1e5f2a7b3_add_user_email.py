"""add users.email (copie de l'email Supabase pour identifier un compte)"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c8d1e5f2a7b3"
down_revision: str | None = "d4e3f0000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "email")
