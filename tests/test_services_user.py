from unittest.mock import AsyncMock

import pytest
from sqlalchemy.sql.dml import Delete

from app.models.favorite import Favorite
from app.services.user import delete_user_data
from app.models.subscription import Subscription


@pytest.mark.asyncio
async def test_delete_user_data_deletes_local_user_rows_then_commits() -> None:
    db = AsyncMock()

    await delete_user_data("user-123", db)

    assert db.execute.await_count == 2
    favorite_statement = db.execute.await_args_list[0].args[0]
    subscription_statement = db.execute.await_args_list[1].args[0]

    assert isinstance(favorite_statement, Delete)
    assert favorite_statement.table.name == Favorite.__tablename__
    assert "user_favorites.user_id = :user_id_1" in str(favorite_statement)

    assert isinstance(subscription_statement, Delete)
    assert subscription_statement.table.name == Subscription.__tablename__
    assert "subscriptions.user_id = :user_id_1" in str(subscription_statement)

    db.commit.assert_awaited_once_with()
