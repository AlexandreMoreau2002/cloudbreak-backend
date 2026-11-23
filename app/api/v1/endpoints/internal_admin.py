import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_redis, require_cron_secret
from app.core.errors import ApiError, ErrorCode
from app.db.session import get_db
from app.models.cron_heartbeat import CronHeartbeat
from app.schemas.admin import HeartbeatRequest, ServerMetricsRequest

router = APIRouter(prefix="/internal", tags=["internal"])
JOBS = {"purge", "favorites", "backup"}


@router.post(
    "/heartbeats/{job}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_cron_secret)],
)
async def heartbeat(
    job: str, body: HeartbeatRequest, db: AsyncSession = Depends(get_db)
) -> Response:
    if job not in JOBS:
        raise ApiError(status.HTTP_404_NOT_FOUND, "Job inconnu", ErrorCode.HEARTBEAT_UNKNOWN_JOB)
    now = datetime.now(UTC)
    record = await db.get(CronHeartbeat, job)
    if record is None:
        record = CronHeartbeat(
            job=job,
            last_run_at=now,
            last_status=body.status,
            last_ok_at=now if body.status == "ok" else None,
        )
        db.add(record)
    else:
        record.last_run_at = now  # type: ignore[assignment]
        record.last_status = body.status  # type: ignore[assignment]
        if body.status == "ok":
            record.last_ok_at = now  # type: ignore[assignment]
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/server-metrics",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_cron_secret)],
)
async def server_metrics(body: ServerMetricsRequest, redis: Redis = Depends(get_redis)) -> Response:
    sampled = (
        body.sampled_at.astimezone(UTC)
        if body.sampled_at.tzinfo
        else body.sampled_at.replace(tzinfo=UTC)
    )
    if abs((datetime.now(UTC) - sampled).total_seconds()) > 300:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Relevé trop ancien", "VALIDATION_ERROR"
        )
    raw = body.model_dump(mode="json")
    raw["sampled_at"] = sampled.isoformat()
    encoded = json.dumps(raw)
    await redis.set("ops:server_metrics:last", encoded, ex=2700)
    lpush_result = redis.lpush("ops:server_metrics:history", encoded)
    if hasattr(lpush_result, "__await__"):
        await lpush_result
    ltrim_result = redis.ltrim("ops:server_metrics:history", 0, 95)
    if hasattr(ltrim_result, "__await__"):
        await ltrim_result
    return Response(status_code=status.HTTP_204_NO_CONTENT)
