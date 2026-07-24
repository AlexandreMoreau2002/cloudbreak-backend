from unittest.mock import AsyncMock

import pytest
from sqlalchemy.sql.dml import Delete

from app.models.favorite import Favorite
from app.models.prediction import Prediction
from app.services.user import delete_user_data
from app.models.subscription import Subscription
from app.models.terrain_validation import TerrainValidation


@pytest.mark.asyncio
async def test_delete_user_data_deletes_local_user_rows_then_commits() -> None:
    db = AsyncMock()

    await delete_user_data("user-123", db)

    assert db.execute.await_count == 4
    validation_statement = db.execute.await_args_list[0].args[0]
    prediction_statement = db.execute.await_args_list[1].args[0]
    favorite_statement = db.execute.await_args_list[2].args[0]
    subscription_statement = db.execute.await_args_list[3].args[0]

    assert isinstance(validation_statement, Delete)
    assert validation_statement.table.name == TerrainValidation.__tablename__
    assert "terrain_validations.user_id = :user_id_1" in str(validation_statement)

    assert isinstance(prediction_statement, Delete)
    assert prediction_statement.table.name == Prediction.__tablename__
    assert "predictions.user_id = :user_id_1" in str(prediction_statement)

    assert isinstance(favorite_statement, Delete)
    assert favorite_statement.table.name == Favorite.__tablename__
    assert "user_favorites.user_id = :user_id_1" in str(favorite_statement)

    assert isinstance(subscription_statement, Delete)
    assert subscription_statement.table.name == Subscription.__tablename__
    assert "subscriptions.user_id = :user_id_1" in str(subscription_statement)

    db.commit.assert_awaited_once_with()
