import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.api.v1.endpoints.user import router as user_router
from app.api.v1.endpoints.peaks import router as peaks_router
from app.api.v1.endpoints.score import router as score_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.favorites import router as favorites_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", extra={"event": "backend_started", "version": settings.app_version})
    yield


app = FastAPI(title="Cloudbreak API", version=settings.app_version, lifespan=lifespan)

app.include_router(peaks_router)
app.include_router(user_router)
app.include_router(score_router)
app.include_router(health_router)
app.include_router(favorites_router)


@app.exception_handler(OperationalError)
async def db_operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    logger.error(
        "database_unavailable",
        extra={"path": request.url.path, "error": type(exc).__name__},
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Base de données indisponible", "code": "DATABASE_UNAVAILABLE"},
    )
