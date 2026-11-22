import re
from datetime import UTC, datetime

from fastapi import APIRouter

from app.core import config
from app.schemas.version import VersionResponse

router = APIRouter()
GIT_SHA_PATTERN = re.compile(r"[0-9a-fA-F]{7,40}")
RELEASE_TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")


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
    tag = settings.git_tag
    has_valid_sha = GIT_SHA_PATTERN.fullmatch(sha) is not None
    return VersionResponse(
        service="backend",
        sha=sha if has_valid_sha else "unknown",
        built_at=_utc_build_timestamp(settings.built_at) if has_valid_sha else None,
        version=settings.app_version,
        tag=tag if has_valid_sha and RELEASE_TAG_PATTERN.fullmatch(tag) else None,
    )
