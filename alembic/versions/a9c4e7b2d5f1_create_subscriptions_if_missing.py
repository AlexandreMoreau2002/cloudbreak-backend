"""create subscriptions table when missing (bases créées sans create_all)"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a9c4e7b2d5f1"
down_revision: str | None = "b7e2d4f6a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("subscriptions"):
        return
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=50), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    # Pas de drop : la table peut préexister (create_all) et contenir des abonnements.
    pass
