from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import String
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Delete

from app.models.favorite import Favorite
from app.services.user import (
    delete_user_data,
    get_or_create_user,
    get_user_profile,
    provision_user,
    update_user_notification_preferences,
    update_user_survey,
    update_user_preferences,
)
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.terrain_validation import TerrainValidation
from app.models.user import User
from app.schemas.user import (
    AcquisitionSource,
    DisplayNameUpdate,
    NotificationPreferencesUpdate,
    PreferencesUpdate,
    Practice,
    SurveyUpdate,
    UserProfile,
)


@pytest.mark.parametrize("value", ["A" * 24, "A" * 25, "  Alex  "])
def test_display_name_accepts_trimmed_values(value: str) -> None:
    assert DisplayNameUpdate(display_name=value).display_name == value.strip()


@pytest.mark.parametrize("value", ["", "   ", "A" * 26])
def test_display_name_rejects_empty_or_too_long_values(value: str) -> None:
    with pytest.raises(ValidationError):
        DisplayNameUpdate(display_name=value)


def test_display_name_nullable_model_column_and_profile() -> None:
    column = User.__table__.c.display_name
    assert isinstance(column.type, String)
    assert column.type.length == 25
    assert column.nullable is True

    user = User(supabase_user_id="user-123", auth_provider="email", display_name="Alex")
    user.created_at = datetime.now(UTC)
    user.converted_at = datetime.now(UTC)
    user.notif_favorites = True
    user.notif_regional = True
    user.notif_terrain = True
    assert UserProfile.model_validate(user).display_name == "Alex"


def test_display_name_accepts_null_and_forbids_extra_fields() -> None:
    assert DisplayNameUpdate(display_name=None).display_name is None
    with pytest.raises(ValidationError):
        DisplayNameUpdate.model_validate({"display_name": "Alex", "unexpected": True})


@pytest.mark.asyncio
async def test_delete_user_data_deletes_local_user_rows_then_commits() -> None:
    db = AsyncMock()

    await delete_user_data("user-123", db)

    assert db.execute.await_count == 5
    validation_statement = db.execute.await_args_list[0].args[0]
    prediction_statement = db.execute.await_args_list[1].args[0]
    favorite_statement = db.execute.await_args_list[2].args[0]
    subscription_statement = db.execute.await_args_list[3].args[0]
    user_statement = db.execute.await_args_list[4].args[0]

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

    assert isinstance(user_statement, Delete)
    assert user_statement.table.name == "users"

    db.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_or_create_existing_profile_does_not_insert() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await get_or_create_user("user-123", "email", db)

    assert actual is profile
    db.execute.assert_awaited_once()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_absent_profile_inserts_then_rereads() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="apple")
    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None
    second_result = MagicMock()
    second_result.scalar_one.return_value = profile
    db = AsyncMock()
    db.execute.side_effect = [first_result, MagicMock(), second_result]

    actual = await get_or_create_user("user-123", "apple", db)

    assert actual is profile
    assert db.execute.await_count == 3
    insert_statement = db.execute.await_args_list[1].args[0]
    assert insert_statement.table.name == "users"
    assert "ON CONFLICT" in str(insert_statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_update_user_survey_preserves_first_answer() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    profile.survey_completed_at = datetime.now(UTC)
    profile.acquisition_source = AcquisitionSource.APP_STORE.value
    profile.practice = Practice.HIKER.value
    profile.newsletter_opt_in = False
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await update_user_survey(
        {"id": "user-123", "auth_provider": "email"},
        SurveyUpdate(
            acquisition_source=AcquisitionSource.INSTAGRAM,
            practice=Practice.PHOTOGRAPHER,
            newsletter_opt_in=True,
        ),
        db,
    )

    assert actual.acquisition_source == AcquisitionSource.APP_STORE.value
    assert actual.practice == Practice.HIKER.value
    assert actual.newsletter_opt_in is False
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_user_survey_preserves_terminal_skip() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    profile.survey_skipped_at = datetime.now(UTC)
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await update_user_survey(
        {"id": "user-123", "auth_provider": "email"},
        SurveyUpdate(
            acquisition_source=AcquisitionSource.GOOGLE_SEARCH,
            practice=Practice.TRAIL_RUNNER,
            newsletter_opt_in=True,
        ),
        db,
    )

    assert actual.survey_skipped_at == profile.survey_skipped_at
    assert actual.acquisition_source is None
    assert actual.practice is None
    assert actual.newsletter_opt_in is None
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_user_preferences_sets_consent_both_ways() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    profile.survey_completed_at = datetime.now(UTC)
    profile.newsletter_opt_in = True
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    withdrawn = await update_user_preferences(
        {"id": "user-123", "auth_provider": "email"},
        PreferencesUpdate(newsletter_opt_in=False),
        db,
    )
    assert withdrawn.newsletter_opt_in is False

    granted = await update_user_preferences(
        {"id": "user-123", "auth_provider": "email"},
        PreferencesUpdate(newsletter_opt_in=True),
        db,
    )
    assert granted.newsletter_opt_in is True
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_update_notification_preferences_partial_update() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    profile.notif_favorites = True
    profile.notif_regional = True
    profile.notif_terrain = True
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    updated = await update_user_notification_preferences(
        {"id": "user-123", "auth_provider": "email"},
        NotificationPreferencesUpdate(notif_regional=False),
        db,
    )

    assert updated.notif_favorites is True
    assert updated.notif_regional is False
    assert updated.notif_terrain is True
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_notification_preferences_empty_payload_no_op() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    profile.notif_favorites = True
    profile.notif_regional = False
    profile.notif_terrain = True
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    updated = await update_user_notification_preferences(
        {"id": "user-123", "auth_provider": "email"},
        NotificationPreferencesUpdate(),
        db,
    )

    assert updated.notif_favorites is True
    assert updated.notif_regional is False
    assert updated.notif_terrain is True
    db.flush.assert_awaited_once()


@pytest.mark.parametrize("field", ["notif_favorites", "notif_regional", "notif_terrain"])
def test_notification_preferences_reject_explicit_null(field: str) -> None:
    with pytest.raises(ValidationError):
        NotificationPreferencesUpdate.model_validate({field: None})


@pytest.mark.asyncio
async def test_get_user_profile_returns_row_or_none() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    found = MagicMock()
    found.scalar_one_or_none.return_value = profile
    absent = MagicMock()
    absent.scalar_one_or_none.return_value = None
    db = AsyncMock()

    db.execute.return_value = found
    assert await get_user_profile("user-123", db) is profile

    db.execute.return_value = absent
    assert await get_user_profile("missing", db) is None


@pytest.mark.asyncio
async def test_provision_user_delegates_to_get_or_create() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="apple")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await provision_user({"id": "user-123", "auth_provider": "apple"}, db)

    assert actual is profile


@pytest.mark.asyncio
async def test_update_user_survey_records_first_answer() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await update_user_survey(
        {"id": "user-123", "auth_provider": "email"},
        SurveyUpdate(
            acquisition_source=AcquisitionSource.INSTAGRAM,
            practice=Practice.PHOTOGRAPHER,
            newsletter_opt_in=True,
        ),
        db,
    )

    assert actual.acquisition_source == AcquisitionSource.INSTAGRAM.value
    assert actual.practice == Practice.PHOTOGRAPHER.value
    assert actual.newsletter_opt_in is True
    assert actual.survey_completed_at is not None
    db.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_update_user_survey_records_first_skip() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await update_user_survey(
        {"id": "user-123", "auth_provider": "email"},
        SurveyUpdate(skipped=True),
        db,
    )

    assert actual.survey_skipped_at is not None
    assert actual.survey_completed_at is None
    assert actual.acquisition_source is None
    db.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_or_create_absent_profile_stores_email_from_token() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None
    second_result = MagicMock()
    second_result.scalar_one.return_value = profile
    db = AsyncMock()
    db.execute.side_effect = [first_result, MagicMock(), second_result]

    await get_or_create_user("user-123", "email", db, email="alex@example.com")

    insert_statement = db.execute.await_args_list[1].args[0]
    assert insert_statement.compile().params["email"] == "alex@example.com"


@pytest.mark.asyncio
async def test_get_or_create_existing_profile_backfills_missing_email() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await get_or_create_user("user-123", "email", db, email="alex@example.com")

    assert actual.email == "alex@example.com"
    db.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_or_create_existing_profile_follows_email_change() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email", email="old@example.com")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await get_or_create_user("user-123", "email", db, email="new@example.com")

    assert actual.email == "new@example.com"


@pytest.mark.asyncio
async def test_get_or_create_existing_profile_keeps_email_when_token_has_none() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email", email="alex@example.com")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await get_or_create_user("user-123", "email", db)

    assert actual.email == "alex@example.com"
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_provision_user_passes_token_email() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await provision_user(
        {"id": "user-123", "auth_provider": "email", "email": "alex@example.com"}, db
    )

    assert actual.email == "alex@example.com"


@pytest.mark.asyncio
async def test_provision_user_ignores_non_string_email() -> None:
    profile = User(supabase_user_id="user-123", auth_provider="email")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = AsyncMock()
    db.execute.return_value = result

    actual = await provision_user({"id": "user-123", "email": 42}, db)

    assert actual.email is None
