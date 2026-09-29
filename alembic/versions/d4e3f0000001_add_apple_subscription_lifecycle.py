"""add Apple subscription lifecycle columns and notification ledger"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d4e3f0000001"
down_revision: str | None = "b7e2d4f6a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("status", sa.String(length=50), nullable=False, server_default="none"),
    )
    op.add_column("subscriptions", sa.Column("original_transaction_id", sa.String(length=255)))
    op.add_column("subscriptions", sa.Column("latest_transaction_id", sa.String(length=255)))
    op.add_column("subscriptions", sa.Column("apple_environment", sa.String(length=50)))
    op.create_unique_constraint(
        "uq_subscriptions_original_transaction_id", "subscriptions", ["original_transaction_id"]
    )
    op.create_unique_constraint(
        "uq_subscriptions_latest_transaction_id", "subscriptions", ["latest_transaction_id"]
    )
    op.create_table(
        "apple_subscription_events",
        sa.Column("notification_uuid", sa.String(length=255), nullable=False),
        sa.Column("notification_type", sa.String(length=100), nullable=False),
        sa.Column("original_transaction_id", sa.String(length=255), nullable=True),
        sa.Column("signed_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("notification_uuid"),
    )


def downgrade() -> None:
    op.drop_table("apple_subscription_events")
    op.drop_constraint("uq_subscriptions_latest_transaction_id", "subscriptions", type_="unique")
    op.drop_constraint("uq_subscriptions_original_transaction_id", "subscriptions", type_="unique")
    op.drop_column("subscriptions", "apple_environment")
    op.drop_column("subscriptions", "latest_transaction_id")
    op.drop_column("subscriptions", "original_transaction_id")
    op.drop_column("subscriptions", "status")
