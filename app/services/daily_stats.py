from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.daily_stat import DailyStat
from app.models.prediction import Prediction


async def record_snapshot(db: AsyncSession, now: datetime) -> None:
    """Enregistre (ou met à jour) l'instantané du jour : compteurs uniquement."""
    day = now.date()
    start = datetime.combine(day, time.min, UTC)
    users_total = await db.scalar(select(func.count(func.distinct(Prediction.user_id))))
    accounts_total = await db.scalar(select(func.count()).select_from(User))
    checks = await db.scalar(
        select(func.count()).select_from(Prediction).where(Prediction.created_at >= start)
    )
    values = {
        "users_total": int(users_total or 0),
        "accounts_total": int(accounts_total or 0),
        "checks": int(checks or 0),
    }
    statement = insert(DailyStat).values(day=day, **values)
    await db.execute(statement.on_conflict_do_update(index_elements=[DailyStat.day], set_=values))
    await db.flush()


async def snapshots_since(db: AsyncSession, since: date) -> dict[date, int]:
    """`users_total` par jour pour les instantanés dont le jour est >= `since`."""
    rows = await db.execute(
        select(DailyStat.day, DailyStat.users_total).where(DailyStat.day >= since)
    )
    return {day: int(total) for day, total in rows}
