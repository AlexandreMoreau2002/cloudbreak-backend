"""Regression tests for the create-subscriptions-if-missing migration."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic/versions/a9c4e7b2d5f1_create_subscriptions_if_missing.py"
    )
    specification = importlib.util.spec_from_file_location(
        "create_subscriptions_migration", migration_path
    )
    assert specification is not None
    assert specification.loader is not None
    migration = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(migration)
    return migration


def _run_upgrade(table_exists: bool) -> MagicMock:
    migration = _load_migration()
    original_op = migration.op
    migration_op = MagicMock()
    migration.op = migration_op
    try:
        with patch.object(migration.sa, "inspect") as inspect:
            inspect.return_value.has_table.return_value = table_exists
            migration.upgrade()
    finally:
        migration.op = original_op
    return migration_op


def test_upgrade_creates_subscriptions_when_missing() -> None:
    migration_op = _run_upgrade(table_exists=False)

    migration_op.create_table.assert_called_once()
    assert migration_op.create_table.call_args.args[0] == "subscriptions"


def test_upgrade_is_noop_when_subscriptions_exists() -> None:
    migration_op = _run_upgrade(table_exists=True)

    migration_op.create_table.assert_not_called()


def test_downgrade_never_drops_subscriptions() -> None:
    migration = _load_migration()
    original_op = migration.op
    migration_op = MagicMock()
    migration.op = migration_op
    try:
        migration.downgrade()
    finally:
        migration.op = original_op

    migration_op.drop_table.assert_not_called()


def test_lifecycle_migration_now_follows_create_subscriptions() -> None:
    lifecycle_path = (
        Path(__file__).parents[1]
        / "alembic/versions/d4e3f0000001_add_apple_subscription_lifecycle.py"
    )

    assert 'down_revision: str | None = "a9c4e7b2d5f1"' in lifecycle_path.read_text()
