from datetime import UTC, datetime

from fastapi import APIRouter

from app.core import config
from app.schemas.version import VersionResponse

router = APIRouter()


def _utc_build_timestamp(value: str) -> str | None:
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            return None
        return timestamp.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z"
    except (ValueError, OverflowError):
        return None


@router.get("/version")
async def get_version() -> VersionResponse:
    settings = config.settings
    sha = settings.git_sha
    return VersionResponse(
        service="backend",
        sha=sha or "unknown",
        built_at=_utc_build_timestamp(settings.built_at) if sha else None,
        version=settings.app_version,
        tag=(settings.git_tag or None) if sha else None,
    )
