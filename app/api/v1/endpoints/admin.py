import uuid

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_redis, require_admin
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.services.admin_overview import build_overview

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview")
async def overview(
    user: dict[str, object] = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, object]:
    data = await build_overview(db, redis)
    db.add(
        AdminAuditLog(
            id=str(uuid.uuid4()),
            actor_id=str(user["id"]),
            action="read",
            resource="overview",
            result="success",
        )
    )
    await db.commit()
    return data
