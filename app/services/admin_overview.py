from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cron_heartbeat import CronHeartbeat
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.user import User
from app.services import daily_stats
from app.schemas.admin import ServerMetricsRequest


async def build_overview(db: AsyncSession, redis: Redis) -> dict[str, object]:
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)

    async def count(query: object) -> int:
        return int((await db.scalar(cast(Any, query))) or 0)

    permanent = await count(select(func.count()).select_from(User))
    active = await count(
        select(func.count()).select_from(Subscription).where(Subscription.status == "active")
    )
    trial = await count(
        select(func.count()).select_from(Subscription).where(Subscription.status == "trial")
    )
    active_30d = await count(
        select(func.count(func.distinct(Prediction.user_id))).where(
            Prediction.created_at >= now - timedelta(days=30),
            # Comptes de `users` seulement : exclut les sessions anonymes et les comptes supprimés.
            Prediction.user_id.in_(select(User.supabase_user_id)),
        )
    )
    users_total = await count(select(func.count(func.distinct(Prediction.user_id))))
    # Upsert de l'instantané du jour : committé par l'audit de l'endpoint (même session).
    await daily_stats.record_snapshot(db, now)
    permanent_7d = await count(
        select(func.count()).select_from(User).where(User.created_at >= seven_days_ago)
    )
    subscriptions_active_7d = await count(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.status == "active", Subscription.created_at >= seven_days_ago)
    )
    subscriptions_trial_7d = await count(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.status == "trial", Subscription.created_at >= seven_days_ago)
    )
    crons = await db.scalars(select(CronHeartbeat))
    records = {str(entry.job): entry for entry in crons}
    expected = {"purge": 90000, "favorites": 90000, "backup": 93600}
    cron_data = []
    for job, seconds in expected.items():
        row = records.get(job)
        if row is None:
            state, overdue = "never", None
        elif row.last_status == "fail":
            state, overdue = "failed", None
        else:
            last_run_at = cast(datetime, row.last_run_at)
            overdue_seconds = (now - last_run_at).total_seconds() - seconds
            state = "late" if overdue_seconds > 0 else "ok"
            overdue = ceil(overdue_seconds) if state == "late" else None
        cron_data.append(
            {
                "job": job,
                "state": state,
                "last_run_at": row.last_run_at.isoformat() if row else None,
                "last_status": row.last_status if row else None,
                "expected_every_s": seconds,
                "overdue_s": overdue,
            }
        )
    history_raw = redis.lrange("ops:server_metrics:history", 0, 95)
    if hasattr(history_raw, "__await__"):
        history_raw = await history_raw
    valid_history = []
    for value in history_raw:
        try:
            item = ServerMetricsRequest.model_validate_json(value).model_dump(mode="json")
            sampled_at = datetime.fromisoformat(item["sampled_at"].replace("Z", "+00:00"))
            if sampled_at >= now - timedelta(hours=24):
                valid_history.append(item)
        except (TypeError, ValueError):
            continue
    raw = await redis.get("ops:server_metrics:last")
    try:
        metric = (
            ServerMetricsRequest.model_validate_json(raw).model_dump(mode="json") if raw else None
        )
    except (TypeError, ValueError):
        metric = None
    if metric is None and valid_history:
        metric = max(valid_history, key=lambda item: item["sampled_at"])
    sampled = (
        datetime.fromisoformat(metric["sampled_at"].replace("Z", "+00:00")) if metric else None
    )
    server: dict[str, object] = {
        "state": "never" if not metric else "ok",
        "sampled_at": metric.get("sampled_at") if metric else None,
    }
    if metric and sampled is not None and now - sampled > timedelta(minutes=30):
        server["state"] = "stale"
    if metric and server["state"] == "ok":
        server.update(
            {
                "cpu_load_1m": metric["cpu_load_1m"],
                "cpu_count": metric["cpu_count"],
                "mem_available_mb": metric["mem_available_mb"],
                "mem_total_mb": metric["mem_total_mb"],
                "swap_used_mb": metric["swap_used_mb"],
                "swap_total_mb": metric["swap_total_mb"],
                "disk_used_pct": round(metric["disk_used_gb"] / metric["disk_total_gb"] * 100)
                if metric["disk_total_gb"]
                else 0,
                "history_24h": [],
            }
        )
    else:
        server.update(
            {
                "cpu_load_1m": None,
                "cpu_count": None,
                "mem_available_mb": None,
                "mem_total_mb": None,
                "swap_used_mb": None,
                "swap_total_mb": None,
                "disk_used_pct": None,
                "history_24h": [],
            }
        )
    window_start = now.date() - timedelta(days=89)
    prediction_rows = await db.execute(
        select(func.date(Prediction.created_at), func.count())
        .where(Prediction.created_at >= datetime.combine(window_start, datetime.min.time(), UTC))
        .group_by(func.date(Prediction.created_at))
    )
    checks = {str(day): int(count) for day, count in prediction_rows}
    zero_days = [
        {
            "date": (now.date() - timedelta(days=index)).isoformat(),
            "count": checks.get((now.date() - timedelta(days=index)).isoformat(), 0),
        }
        for index in range(13, -1, -1)
    ]
    user_rows = await db.execute(select(User.created_at))
    created_by_day: dict[str, int] = {}
    running_total = 0
    for created_at in user_rows.scalars():
        created_day = created_at.astimezone(UTC).date()
        if created_day < window_start:
            running_total += 1
            continue
        day = created_day.isoformat()
        created_by_day[day] = created_by_day.get(day, 0) + 1
    snapshots = await daily_stats.snapshots_since(db, window_start)
    week_ago = snapshots.get(now.date() - timedelta(days=7))
    series = []
    last_users_total: int | None = None
    for index in range(89, -1, -1):
        day_date = now.date() - timedelta(days=index)
        day = day_date.isoformat()
        running_total += created_by_day.get(day, 0)
        last_users_total = snapshots.get(day_date, last_users_total)
        series.append(
            {
                "date": day,
                "users_total": users_total if index == 0 else last_users_total,
                "users_permanent": running_total,
                "checks": checks.get(day, 0),
            }
        )

    def kpi(value: int, delta_7d: int | None) -> dict[str, int | None]:
        return {"value": value, "delta_7d": delta_7d}

    if server["state"] in {"ok", "stale"}:
        server["history_24h"] = [
            {
                "sampled_at": item["sampled_at"],
                "cpu_load_1m": item["cpu_load_1m"],
                "mem_available_pct": round(item["mem_available_mb"] / item["mem_total_mb"] * 100, 1)
                if item["mem_total_mb"]
                else 0,
                "swap_used_pct": round(item["swap_used_mb"] / item["swap_total_mb"] * 100, 1)
                if item["swap_total_mb"]
                else 0,
                "disk_used_pct": round(item["disk_used_gb"] / item["disk_total_gb"] * 100)
                if item["disk_total_gb"]
                else 0,
            }
            for item in sorted(valid_history, key=lambda item: item["sampled_at"])
        ]
    return {
        "generated_at": now.isoformat(),
        "kpis": {
            "users_total": kpi(users_total, None if week_ago is None else users_total - week_ago),
            "users_permanent": kpi(permanent, permanent_7d),
            "users_active_30d": kpi(active_30d, 0),
            "subscriptions_active": kpi(active, subscriptions_active_7d),
            "subscriptions_trial": kpi(trial, subscriptions_trial_7d),
        },
        "checks_daily": zero_days,
        "series_90d": series,
        "crons": cron_data,
        "server": server,
    }
