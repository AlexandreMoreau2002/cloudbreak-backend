"""Tests for the users.push_token migration."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import Boolean, String

from app.models.user import User

FILENAME = "a5b1c2d3e4f5_add_user_push_token.py"


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions" / FILENAME
    spec = importlib.util.spec_from_file_location("add_user_push_token_migration", path)
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


def test_upgrade_adds_token_and_validity_columns() -> None:
    migration_op = _run("upgrade")

    assert migration_op.add_column.call_count == 2
    columns = {call.args[1].name: call.args[1] for call in migration_op.add_column.call_args_list}
    assert isinstance(columns["push_token"].type, String)
    assert columns["push_token"].type.length == 255
    assert columns["push_token"].nullable is True
    assert isinstance(columns["push_token_valid"].type, Boolean)
    assert columns["push_token_valid"].nullable is False
    assert str(columns["push_token_valid"].server_default.arg) == "true"


def test_upgrade_creates_partial_unique_push_token_index() -> None:
    migration_op = _run("upgrade")

    migration_op.create_index.assert_called_once()
    call = migration_op.create_index.call_args
    assert call.args == ("ix_users_push_token", "users", ["push_token"])
    assert call.kwargs["unique"] is True
    assert str(call.kwargs["postgresql_where"]) == "push_token IS NOT NULL"


def test_downgrade_drops_index_before_columns() -> None:
    migration_op = _run("downgrade")

    names = [call[0] for call in migration_op.mock_calls]
    assert names.index("drop_index") < names.index("drop_column")
    migration_op.drop_index.assert_called_once_with("ix_users_push_token", table_name="users")


def test_model_index_matches_migration() -> None:
    indexes = {index.name: index for index in User.__table__.indexes}
    index = indexes["ix_users_push_token"]
    assert index.unique is True
    assert str(index.dialect_options["postgresql"]["where"]) == "push_token IS NOT NULL"
    assert [column.name for column in index.columns] == ["push_token"]


def test_downgrade_drops_both_columns() -> None:
    migration_op = _run("downgrade")

    dropped = [call.args for call in migration_op.drop_column.call_args_list]
    assert ("users", "push_token_valid") in dropped
    assert ("users", "push_token") in dropped


def test_migration_follows_previous_head() -> None:
    assert _load_migration().down_revision == "fb27705a94f7"


def test_model_columns_match_migration() -> None:
    assert isinstance(User.__table__.c.push_token.type, String)
    assert User.__table__.c.push_token.nullable is True
    assert isinstance(User.__table__.c.push_token_valid.type, Boolean)
    assert User.__table__.c.push_token_valid.nullable is False
    assert str(User.__table__.c.push_token_valid.server_default.arg) == "true"
