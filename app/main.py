import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from app.api.v1.endpoints.user import router as user_router
from app.api.v1.endpoints.score import router as score_router
from app.api.v1.endpoints.peaks import router as peaks_router
from app.api.v1.endpoints.health import router as health_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", extra={"event": "backend_started", "version": "1.0.0"})
    yield


app = FastAPI(title="Cloudbreak API", version="1.0.0", lifespan=lifespan)

app.include_router(peaks_router)
app.include_router(user_router)
app.include_router(score_router)
app.include_router(health_router)
