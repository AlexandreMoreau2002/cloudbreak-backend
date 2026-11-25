import json
import re
from datetime import UTC, datetime

from pathlib import Path

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


BUILD_INFO_PATH = Path(__file__).resolve().parents[4] / "build_info.json"


def _build_info() -> tuple[str, str, str]:
    """Variables d'environnement d'abord, sinon build_info.json écrit au build."""
    settings = config.settings
    if settings.git_sha:
        return settings.git_sha, settings.built_at, settings.git_tag
    try:
        data = json.loads(BUILD_INFO_PATH.read_text())
        return (
            str(data.get("sha") or ""),
            str(data.get("built_at") or ""),
            str(data.get("tag") or ""),
        )
    except (OSError, ValueError, AttributeError):
        return "", "", ""


@router.get("/version")
async def get_version() -> VersionResponse:
    settings = config.settings
    sha, built_at, tag = _build_info()
    has_valid_sha = GIT_SHA_PATTERN.fullmatch(sha) is not None
    return VersionResponse(
        service="backend",
        sha=sha if has_valid_sha else "unknown",
        built_at=_utc_build_timestamp(built_at) if has_valid_sha else None,
        version=settings.app_version,
        tag=tag if has_valid_sha and RELEASE_TAG_PATTERN.fullmatch(tag) else None,
    )
