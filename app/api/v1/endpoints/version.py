from fastapi import APIRouter

from app.core import config
from app.schemas.version import VersionResponse

router = APIRouter()


@router.get("/version")
async def get_version() -> VersionResponse:
    settings = config.settings
    sha = settings.git_sha
    return VersionResponse(
        service="backend",
        sha=sha or "unknown",
        built_at=(settings.built_at or None) if sha else None,
        version=settings.app_version,
        tag=settings.git_tag or None,
    )
