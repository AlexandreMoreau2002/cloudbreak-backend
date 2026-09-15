from enum import StrEnum
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


class AcquisitionSource(StrEnum):
    APP_STORE = "app_store"
    GOOGLE_SEARCH = "google_search"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    WORD_OF_MOUTH = "word_of_mouth"
    OTHER = "other"


class Practice(StrEnum):
    HIKER = "hiker"
    TRAIL_RUNNER = "trail_runner"
    PARAGLIDER = "paraglider"
    PHOTOGRAPHER = "photographer"
    MOUNTAINEER = "mountaineer"
    OTHER = "other"


class SurveyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acquisition_source: AcquisitionSource | None = None
    practice: Practice | None = None
    newsletter_opt_in: bool | None = None
    skipped: bool = False


class PreferencesUpdate(BaseModel):
    """Consentements modifiables à tout moment (RGPD art. 7-3)."""

    model_config = ConfigDict(extra="forbid")

    newsletter_opt_in: bool


class NotificationPreferencesUpdate(BaseModel):
    """Update partiel — chaque préférence est indépendante et optionnelle."""

    model_config = ConfigDict(extra="forbid")

    notif_favorites: bool | None = None
    notif_regional: bool | None = None
    notif_terrain: bool | None = None

    @field_validator("notif_favorites", "notif_regional", "notif_terrain")
    @classmethod
    def reject_explicit_null(cls, value: bool | None) -> bool | None:
        if value is None:
            raise ValueError("Notification preferences cannot be null")
        return value


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supabase_user_id: str
    auth_provider: str
    created_at: datetime
    converted_at: datetime
    survey_completed_at: datetime | None = None
    survey_skipped_at: datetime | None = None
    acquisition_source: str | None = None
    practice: str | None = None
    newsletter_opt_in: bool | None = None
    notif_favorites: bool
    notif_regional: bool
    notif_terrain: bool
