from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import _audit_admin_overview, get_redis, require_admin
from app.db.session import get_db
from app.services.admin_overview import build_overview

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview")
async def overview(
    user: dict[str, object] = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, object]:
    try:
        data = await build_overview(db, redis)
    except Exception:
        await db.rollback()
        await _audit_admin_overview(db, str(user["id"]), "error")
        raise
    await _audit_admin_overview(db, str(user["id"]), "success")
    return data
