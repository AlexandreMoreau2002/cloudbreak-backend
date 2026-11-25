"""Tests for the users.email migration and model column."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import String

from app.models.user import User


def _load_migration():
    migration_path = Path(__file__).parents[1] / "alembic/versions/c8d1e5f2a7b3_add_user_email.py"
    specification = importlib.util.spec_from_file_location(
        "add_user_email_migration", migration_path
    )
    assert specification is not None
    assert specification.loader is not None
    migration = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(migration)
    return migration


def _run(direction: str) -> MagicMock:
    migration = _load_migration()
    original_op = migration.op
    migration_op = MagicMock()
    migration.op = migration_op
    try:
        getattr(migration, direction)()
    finally:
        migration.op = original_op
    return migration_op


def test_user_email_column_is_nullable_string() -> None:
    column = User.__table__.c.email

    assert isinstance(column.type, String)
    assert column.type.length == 320
    assert column.nullable is True


def test_upgrade_adds_nullable_email_column() -> None:
    migration_op = _run("upgrade")

    migration_op.add_column.assert_called_once()
    table, column = migration_op.add_column.call_args.args
    assert table == "users"
    assert column.name == "email"
    assert column.nullable is True


def test_downgrade_drops_email_column() -> None:
    migration_op = _run("downgrade")

    migration_op.drop_column.assert_called_once_with("users", "email")


def test_migration_follows_current_head() -> None:
    migration = _load_migration()

    assert migration.down_revision == "d4e3f0000001"
