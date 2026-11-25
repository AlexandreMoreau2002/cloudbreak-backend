"""Regression tests for the Apple subscription lifecycle migration."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import DateTime


def test_lifecycle_migration_backfills_existing_premium_and_pro_statuses() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic/versions/d4e3f0000001_add_apple_subscription_lifecycle.py"
    )
    specification = importlib.util.spec_from_file_location(
        "apple_lifecycle_migration", migration_path
    )
    assert specification is not None
    assert specification.loader is not None
    migration = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(migration)
    original_op = migration.op
    migration_op = MagicMock()
    migration.op = migration_op
    try:
        migration.upgrade()
    finally:
        migration.op = original_op

    migration_op.execute.assert_called_once_with(
        "UPDATE subscriptions SET status = 'active' WHERE plan IN ('premium', 'pro')"
    )


def test_period_watermark_migration_adds_nullable_column_without_backfill() -> None:
    migration_path = (
        Path(__file__).parents[1] / "alembic/versions/e5f4a0000002_add_apple_period_expires_at.py"
    )
    specification = importlib.util.spec_from_file_location(
        "apple_period_watermark_migration", migration_path
    )
    assert specification is not None
    assert specification.loader is not None
    migration = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(migration)
    original_op = migration.op
    migration_op = MagicMock()
    migration.op = migration_op
    try:
        migration.upgrade()
    finally:
        migration.op = original_op

    migration_op.add_column.assert_called_once()
    table, column = migration_op.add_column.call_args.args
    assert table == "subscriptions"
    assert column.name == "apple_period_expires_at"
    assert column.nullable is True
    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True
    migration_op.execute.assert_not_called()
    migration_op.alter_column.assert_not_called()
