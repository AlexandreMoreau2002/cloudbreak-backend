from datetime import UTC, datetime, timedelta
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cron_heartbeat import CronHeartbeat
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.admin import ServerMetricsRequest


async def build_overview(db: AsyncSession, redis: Redis) -> dict[str, object]:
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)

    async def count(query: object) -> int:
        return int((await db.scalar(cast(Any, query))) or 0)

    users = await count(select(func.count()).select_from(User))
    anonymous = await count(
        select(func.count()).select_from(User).where(User.auth_provider == "anonymous")
    )
    permanent = users - anonymous
    active = await count(
        select(func.count()).select_from(Subscription).where(Subscription.status == "active")
    )
    trial = await count(
        select(func.count()).select_from(Subscription).where(Subscription.status == "trial")
    )
    active_30d = await count(
        select(func.count(func.distinct(Prediction.user_id))).where(
            Prediction.created_at >= now - timedelta(days=30)
        )
    )
    users_7d = await count(
        select(func.count()).select_from(User).where(User.created_at <= seven_days_ago)
    )
    anonymous_7d = await count(
        select(func.count())
        .select_from(User)
        .where(User.auth_provider == "anonymous", User.created_at <= seven_days_ago)
    )
    active_7d = await count(
        select(func.count(func.distinct(Prediction.user_id))).where(
            Prediction.created_at >= seven_days_ago - timedelta(days=30),
            Prediction.created_at < seven_days_ago,
        )
    )
    subscriptions_active_7d = await count(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.status == "active", Subscription.created_at <= seven_days_ago)
    )
    subscriptions_trial_7d = await count(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.status == "trial", Subscription.created_at <= seven_days_ago)
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
            overdue = max(0, int((now - last_run_at).total_seconds()) - seconds)
            state = "late" if overdue else "ok"
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
    raw = await redis.get("ops:server_metrics:last")
    try:
        metric = (
            ServerMetricsRequest.model_validate_json(raw).model_dump(mode="json") if raw else None
        )
    except (TypeError, ValueError):
        metric = None
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
    user_rows = await db.execute(select(User.created_at, User.auth_provider))
    created_by_day: dict[str, tuple[int, int]] = {}
    running_total = 0
    running_anonymous = 0
    for created_at, provider in user_rows:
        created_day = cast(datetime, created_at).astimezone(UTC).date()
        if created_day < window_start:
            running_total += 1
            running_anonymous += provider == "anonymous"
            continue
        day = created_day.isoformat()
        totals = created_by_day.get(day, (0, 0))
        created_by_day[day] = (totals[0] + 1, totals[1] + (provider == "anonymous"))
    series = []
    for index in range(89, -1, -1):
        day = (now.date() - timedelta(days=index)).isoformat()
        created = created_by_day.get(day, (0, 0))
        running_total += created[0]
        running_anonymous += created[1]
        series.append(
            {
                "date": day,
                "users_total": running_total,
                "users_permanent": running_total - running_anonymous,
                "users_anonymous": running_anonymous,
                "checks": checks.get(day, 0),
            }
        )

    def kpi(value: int, baseline: int) -> dict[str, int]:
        return {"value": value, "delta_7d": value - baseline}

    history_raw = redis.lrange("ops:server_metrics:history", 0, 95)
    if hasattr(history_raw, "__await__"):
        history_raw = await history_raw
    if server["state"] == "ok":
        valid_history = []
        for value in history_raw:
            try:
                item = ServerMetricsRequest.model_validate_json(value).model_dump(mode="json")
                sampled_at = datetime.fromisoformat(item["sampled_at"].replace("Z", "+00:00"))
                if sampled_at >= now - timedelta(hours=24):
                    valid_history.append(item)
            except (TypeError, ValueError):
                continue
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
            "users_total": kpi(users, users_7d),
            "users_permanent": kpi(permanent, users_7d - anonymous_7d),
            "users_anonymous": kpi(anonymous, anonymous_7d),
            "users_active_30d": kpi(active_30d, active_7d),
            "subscriptions_active": kpi(active, subscriptions_active_7d),
            "subscriptions_trial": kpi(trial, subscriptions_trial_7d),
        },
        "checks_daily": zero_days,
        "series_90d": series,
        "crons": cron_data,
        "server": server,
    }
