"""Tests for the users.locale migration."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import String

from app.models.user import User

FILENAME = "b7c8d9e0f1a2_add_user_locale.py"


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions" / FILENAME
    spec = importlib.util.spec_from_file_location("add_user_locale_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_upgrade_adds_nullable_locale_without_default() -> None:
    migration_op = _run("upgrade")

    migration_op.add_column.assert_called_once()
    table, column = migration_op.add_column.call_args.args
    assert table == "users"
    assert column.name == "locale"
    assert isinstance(column.type, String)
    assert column.type.length == 5
    assert column.nullable is True
    assert column.server_default is None


def test_downgrade_drops_locale() -> None:
    migration_op = _run("downgrade")

    migration_op.drop_column.assert_called_once_with("users", "locale")


def test_migration_follows_previous_head() -> None:
    assert _load_migration().down_revision == "a5b1c2d3e4f5"


def test_model_column_matches_migration() -> None:
    assert isinstance(User.__table__.c.locale.type, String)
    assert User.__table__.c.locale.type.length == 5
    assert User.__table__.c.locale.nullable is True
    assert User.__table__.c.locale.server_default is None
