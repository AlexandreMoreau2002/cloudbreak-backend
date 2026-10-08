"""Tests for the users.display_name migration."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import String

from app.models.user import User


def _load_migration():
    migration_path = (
        Path(__file__).parents[1] / "alembic/versions/fb27705a94f7_add_user_display_name.py"
    )
    specification = importlib.util.spec_from_file_location(
        "add_user_display_name_migration", migration_path
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


def test_display_name_migration_adds_nullable_string_column() -> None:
    migration_op = _run("upgrade")

    migration_op.add_column.assert_called_once()
    table, column = migration_op.add_column.call_args.args
    assert table == "users"
    assert column.name == "display_name"
    assert isinstance(column.type, String)
    assert column.type.length == 25
    assert column.nullable is True


def test_display_name_migration_downgrade_drops_only_column() -> None:
    migration_op = _run("downgrade")

    migration_op.drop_column.assert_called_once_with("users", "display_name")
    assert len(migration_op.mock_calls) == 1


def test_display_name_migration_follows_previous_head() -> None:
    assert _load_migration().down_revision == "e5f4a0000002"


def test_display_name_model_column_matches_migration() -> None:
    column = User.__table__.c.display_name
    assert isinstance(column.type, String)
    assert column.type.length == 25
    assert column.nullable is True
