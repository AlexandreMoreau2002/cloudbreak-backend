import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import ApiError, ErrorCode, log_server_error
from app.core.config import settings
from app.core.sentry import initialize_sentry
from app.services.analytics import initialize_analytics, shutdown_analytics
from app.api.v1.endpoints.user import router as user_router
from app.api.v1.endpoints.peaks import router as peaks_router
from app.api.v1.endpoints.score import router as score_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.version import router as version_router
from app.api.v1.endpoints.favorites import router as favorites_router
from app.api.v1.endpoints.validations import router as validations_router
from app.api.v1.endpoints.internal_maintenance import router as internal_maintenance_router
from app.api.v1.endpoints.internal_notifications import router as internal_notifications_router
from app.api.v1.endpoints.internal_admin import router as internal_admin_router
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.subscription import (
    router as subscription_router,
    webhook_router as apple_webhook_router,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", extra={"event": "backend_started", "version": settings.app_version})
    try:
        yield
    finally:
        shutdown_analytics()


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Sérialise les erreurs métier avec un code au premier niveau."""
    if exc.status_code >= 500:
        log_server_error(request.url.path, exc.status_code, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


async def db_operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    log_server_error(request.url.path, 503, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Base de données indisponible", "code": "DATABASE_UNAVAILABLE"},
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Garde la réponse par défaut de FastAPI et journalise les 5xx."""
    if exc.status_code >= 500:
        log_server_error(request.url.path, exc.status_code, exc)
    return await http_exception_handler(request, exc)  # type: ignore[return-value]


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Toute exception non gérée : 500 JSON générique, journalisé sans stack trace."""
    log_server_error(request.url.path, 500, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Erreur interne", "code": ErrorCode.INTERNAL_ERROR},
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
    application.include_router(version_router)
    application.include_router(favorites_router)
    application.include_router(validations_router)
    application.include_router(subscription_router)
    application.include_router(apple_webhook_router)
    application.include_router(internal_notifications_router)
    application.include_router(internal_maintenance_router)
    application.include_router(internal_admin_router)
    application.include_router(admin_router)

    application.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(OperationalError, db_operational_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(Exception, unhandled_error_handler)
    return application


initialize_sentry(settings.sentry_dsn, settings.environment, settings.app_version)
initialize_analytics(settings.posthog_api_key, settings.posthog_host)
app = create_app(settings.environment)
