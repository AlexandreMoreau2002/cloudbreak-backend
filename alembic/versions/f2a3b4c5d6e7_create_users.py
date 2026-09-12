"""create users application profiles"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("supabase_user_id", sa.String(255), nullable=False),
        sa.Column("auth_provider", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("survey_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("survey_skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acquisition_source", sa.String(50), nullable=True),
        sa.Column("practice", sa.String(50), nullable=True),
        sa.Column("newsletter_opt_in", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("supabase_user_id"),
    )


def downgrade() -> None:
    op.drop_table("users")
