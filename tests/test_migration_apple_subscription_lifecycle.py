"""Regression tests for the Apple subscription lifecycle migration."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock


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
