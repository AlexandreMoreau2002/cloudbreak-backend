from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


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
