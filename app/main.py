import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.core.errors import ApiError
from app.core.config import settings
from app.api.v1.endpoints.user import router as user_router
from app.api.v1.endpoints.peaks import router as peaks_router
from app.api.v1.endpoints.score import router as score_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.favorites import router as favorites_router
from app.api.v1.endpoints.validations import router as validations_router
from app.api.v1.endpoints.internal_maintenance import router as internal_maintenance_router
from app.api.v1.endpoints.internal_notifications import router as internal_notifications_router
from app.api.v1.endpoints.subscription import (
    router as subscription_router,
    webhook_router as apple_webhook_router,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", extra={"event": "backend_started", "version": settings.app_version})
    yield


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Sérialise les erreurs métier avec un code au premier niveau."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


async def db_operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    logger.error(
        "database_unavailable",
        extra={"path": request.url.path, "error": type(exc).__name__},
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Base de données indisponible", "code": "DATABASE_UNAVAILABLE"},
    )


def create_app(environment: str) -> FastAPI:
    """Construit l'application ; Swagger/ReDoc/OpenAPI sont coupés en production."""
    docs_enabled = environment.lower() != "production"
    application = FastAPI(
        title="Cloudbreak API",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    application.include_router(peaks_router)
    application.include_router(user_router)
    application.include_router(score_router)
    application.include_router(health_router)
    application.include_router(favorites_router)
    application.include_router(validations_router)
    application.include_router(subscription_router)
    application.include_router(apple_webhook_router)
    application.include_router(internal_notifications_router)
    application.include_router(internal_maintenance_router)

    application.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(OperationalError, db_operational_error_handler)  # type: ignore[arg-type]
    return application


app = create_app(settings.environment)
