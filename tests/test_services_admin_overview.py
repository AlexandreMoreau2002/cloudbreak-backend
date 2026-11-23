import json
from unittest.mock import AsyncMock
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime, timedelta, tzinfo

import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.peak import Peak
from app.models.user import User
from app.services import admin_overview
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.cron_heartbeat import CronHeartbeat


NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def migrated_postgresql_url(
    postgresql_database_url: URL, upgrade_postgresql: Callable[[str], None]
) -> URL:
    upgrade_postgresql("head")
    return postgresql_database_url


@pytest.fixture
async def db(migrated_postgresql_url: URL) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_postgresql_url)
    try:
        async with AsyncSession(engine) as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def freeze_overview_time(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(admin_overview, "datetime", FixedDatetime)


@pytest.fixture
def redis() -> AsyncMock:
    client = AsyncMock(spec=Redis)
    client.get = AsyncMock(return_value=None)
    client.lrange = AsyncMock(return_value=[])
    return client


@pytest.fixture
async def peak_id(db: AsyncSession) -> str:
    db.add(Peak(id="test-peak", slug="test-peak", name="Test", lat=45, lng=5, altitude=1500))
    await db.flush()
    return "test-peak"


def _prediction(peak_id: str, user_id: str, created_at: datetime) -> Prediction:
    return Prediction(
        peak_id=peak_id,
        user_id=user_id,
        date="2026-12-01",
        hour=7,
        score=80,
        verdict="good",
        cloud_base=1200,
        created_at=created_at,
    )


async def test_overview_counts_permanent_accounts_and_recent_creations(
    db: AsyncSession, redis: AsyncMock, peak_id: str
) -> None:
    db.add_all(
        User(supabase_user_id=user_id, auth_provider=provider, created_at=NOW - timedelta(days=age))
        for user_id, provider, age in [
            ("permanent-old", "email", 40),
            ("anonymous-old", "anonymous", 35),
            ("active-old", "google", 31),
            ("permanent-at-cutoff", "google", 7),
            ("permanent-new", "apple", 2),
            ("anonymous-new", "anonymous", 1),
        ]
    )
    db.add_all(
        Subscription(user_id=user_id, status=status, created_at=NOW - timedelta(days=age))
        for user_id, status, age in [
            ("permanent-old", "active", 15),
            ("permanent-new", "active", 2),
            ("anonymous-old", "trial", 14),
            ("permanent-at-cutoff", "trial", 7),
            ("anonymous-new", "trial", 1),
            ("expired-user", "expired", 10),
            ("revoked-user", "revoked", 1),
        ]
    )
    db.add_all(
        _prediction(peak_id, user_id, NOW - timedelta(days=age))
        for user_id, age in [
            ("permanent-old", 37),
            ("permanent-old", 37),
            ("anonymous-old", 34),
            ("active-old", 29),
            ("active-old", 10),
            ("permanent-at-cutoff", 7),
            ("permanent-at-cutoff", 0),
        ]
    )
    await db.flush()

    overview = await admin_overview.build_overview(db, redis)

    assert overview["kpis"] == {
        "users_permanent": {"value": 6, "delta_7d": 3},
        "users_active_30d": {"value": 2, "delta_7d": 0},
        "subscriptions_active": {"value": 2, "delta_7d": 1},
        "subscriptions_trial": {"value": 3, "delta_7d": 2},
    }


async def test_overview_returns_all_fourteen_check_dates_on_empty_database(
    db: AsyncSession, redis: AsyncMock
) -> None:
    overview = await admin_overview.build_overview(db, redis)

    assert overview["checks_daily"] == [
        {"date": f"2026-11-{day}", "count": 0} for day in range(10, 24)
    ]


async def test_ninety_day_series_keeps_prior_users_and_fills_days_without_checks(
    db: AsyncSession, redis: AsyncMock, peak_id: str
) -> None:
    db.add_all(
        [
            User(
                supabase_user_id="pre-window",
                auth_provider="email",
                created_at=datetime(2026, 8, 25, 23, 59, tzinfo=UTC),
            ),
            User(
                supabase_user_id="first-day",
                auth_provider="anonymous",
                created_at=datetime(2026, 8, 26, tzinfo=UTC),
            ),
            User(
                supabase_user_id="last-day",
                auth_provider="google",
                created_at=datetime(2026, 11, 23, tzinfo=UTC),
            ),
            _prediction(peak_id, "pre-window", datetime(2026, 8, 25, 23, 59, tzinfo=UTC)),
            _prediction(peak_id, "first-day", datetime(2026, 8, 26, tzinfo=UTC)),
            _prediction(peak_id, "first-day", datetime(2026, 11, 22, 8, tzinfo=UTC)),
            _prediction(peak_id, "first-day", datetime(2026, 11, 22, 16, tzinfo=UTC)),
            _prediction(peak_id, "last-day", NOW),
        ]
    )
    await db.flush()

    overview = await admin_overview.build_overview(db, redis)

    series = overview["series_90d"]
    assert [day["date"] for day in series] == [
        (date(2026, 8, 26) + timedelta(days=offset)).isoformat() for offset in range(90)
    ]
    assert [(day["date"], day["checks"]) for day in series if day["checks"]] == [
        ("2026-08-26", 1),
        ("2026-11-22", 2),
        ("2026-11-23", 1),
    ]
    assert [day["users_permanent"] for day in series] == [2] * 89 + [3]
    assert overview["checks_daily"][-3:] == [
        {"date": "2026-11-21", "count": 0},
        {"date": "2026-11-22", "count": 2},
        {"date": "2026-11-23", "count": 1},
    ]


async def test_overview_classifies_on_time_late_and_failed_crons(
    db: AsyncSession, redis: AsyncMock
) -> None:
    purge_at = NOW - timedelta(hours=25)
    backup_at = NOW - timedelta(hours=26, seconds=17)
    failed_at = NOW - timedelta(days=3)
    db.add_all(
        [
            CronHeartbeat(job="purge", last_run_at=purge_at, last_status="ok"),
            CronHeartbeat(job="backup", last_run_at=backup_at, last_status="ok"),
            CronHeartbeat(job="favorites", last_run_at=failed_at, last_status="fail"),
        ]
    )
    await db.flush()

    overview = await admin_overview.build_overview(db, redis)

    by_job = {row["job"]: row for row in overview["crons"]}
    assert {job: row["state"] for job, row in by_job.items()} == {
        "purge": "ok",
        "favorites": "failed",
        "backup": "late",
    }
    assert by_job["favorites"] == {
        "job": "favorites",
        "state": "failed",
        "last_run_at": failed_at.isoformat(),
        "last_status": "fail",
        "expected_every_s": 90000,
        "overdue_s": None,
    }
    assert by_job["backup"] == {
        "job": "backup",
        "state": "late",
        "last_run_at": backup_at.isoformat(),
        "last_status": "ok",
        "expected_every_s": 93600,
        "overdue_s": 17,
    }
    assert by_job["purge"]["overdue_s"] is None


async def test_overview_marks_a_cron_late_immediately_after_its_deadline(
    db: AsyncSession, redis: AsyncMock
) -> None:
    db.add(
        CronHeartbeat(
            job="purge",
            last_run_at=NOW - timedelta(seconds=90000, milliseconds=500),
            last_status="ok",
        )
    )
    await db.flush()

    overview = await admin_overview.build_overview(db, redis)

    assert overview["crons"][0]["state"] == "late"
    assert overview["crons"][0]["overdue_s"] == 1


async def test_overview_reports_never_for_jobs_without_heartbeats(
    db: AsyncSession, redis: AsyncMock
) -> None:
    overview = await admin_overview.build_overview(db, redis)

    assert overview["crons"] == [
        {
            "job": job,
            "state": "never",
            "last_run_at": None,
            "last_status": None,
            "expected_every_s": expected,
            "overdue_s": None,
        }
        for job, expected in [("purge", 90000), ("favorites", 90000), ("backup", 93600)]
    ]


def _metrics(sampled_at: str, *, idle: bool = False) -> bytes:
    return json.dumps(
        {
            "sampled_at": sampled_at,
            "cpu_load_1m": 0.5,
            "cpu_count": 4,
            "mem_total_mb": 0 if idle else 4096,
            "mem_available_mb": 0 if idle else 1536,
            "swap_total_mb": 0 if idle else 512,
            "swap_used_mb": 0 if idle else 64,
            "disk_total_gb": 0 if idle else 80,
            "disk_used_gb": 0 if idle else 44,
        }
    ).encode()


async def test_overview_returns_fresh_server_gauges_and_ordered_history(
    db: AsyncSession, redis: AsyncMock
) -> None:
    latest = "2026-11-23T11:30:00Z"
    oldest = "2026-11-22T12:00:00Z"
    redis.get.return_value = _metrics(latest)
    redis.lrange.return_value = [
        _metrics(latest),
        b"invalid",
        _metrics("2026-11-22T11:59:59Z"),
        _metrics(oldest, idle=True),
    ]

    overview = await admin_overview.build_overview(db, redis)

    assert overview["server"] == {
        "state": "ok",
        "sampled_at": latest,
        "cpu_load_1m": 0.5,
        "cpu_count": 4,
        "mem_available_mb": 1536,
        "mem_total_mb": 4096,
        "swap_used_mb": 64,
        "swap_total_mb": 512,
        "disk_used_pct": 55,
        "history_24h": [
            {
                "sampled_at": oldest,
                "cpu_load_1m": 0.5,
                "mem_available_pct": 0,
                "swap_used_pct": 0,
                "disk_used_pct": 0,
            },
            {
                "sampled_at": latest,
                "cpu_load_1m": 0.5,
                "mem_available_pct": 37.5,
                "swap_used_pct": 12.5,
                "disk_used_pct": 55,
            },
        ],
    }


@pytest.mark.parametrize(
    ("latest", "history", "expected_state", "expected_sampled_at", "expected_history"),
    [
        (
            _metrics("2026-11-23T11:29:59Z"),
            [_metrics("2026-11-23T11:29:59Z")],
            "stale",
            "2026-11-23T11:29:59Z",
            1,
        ),
        (None, [], "never", None, 0),
        (
            b"invalid",
            [_metrics("2026-11-23T11:14:00Z")],
            "stale",
            "2026-11-23T11:14:00Z",
            1,
        ),
    ],
    ids=["stale", "missing", "invalid"],
)
async def test_overview_hides_unavailable_server_gauges(
    db: AsyncSession,
    redis: AsyncMock,
    latest: bytes | None,
    history: list[bytes],
    expected_state: str,
    expected_sampled_at: str | None,
    expected_history: int,
) -> None:
    redis.get.return_value = latest
    redis.lrange.return_value = history

    overview = await admin_overview.build_overview(db, redis)

    assert overview["server"] == {
        "state": expected_state,
        "sampled_at": expected_sampled_at,
        "cpu_load_1m": None,
        "cpu_count": None,
        "mem_available_mb": None,
        "mem_total_mb": None,
        "swap_used_mb": None,
        "swap_total_mb": None,
        "disk_used_pct": None,
        "history_24h": [
            {
                "sampled_at": expected_sampled_at,
                "cpu_load_1m": 0.5,
                "mem_available_pct": 37.5,
                "swap_used_pct": 12.5,
                "disk_used_pct": 55,
            }
        ]
        if expected_history
        else [],
    }
