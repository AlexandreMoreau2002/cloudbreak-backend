from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.peak import Peak
from app.models.user import User
from app.services import daily_stats
from app.models.daily_stat import DailyStat
from app.models.prediction import Prediction

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
            await session.rollback()
    finally:
        await engine.dispose()


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


async def test_record_snapshot_counts_distinct_users_accounts_and_checks_of_the_day(
    db: AsyncSession, peak_id: str
) -> None:
    db.add(User(supabase_user_id="acc", auth_provider="email", created_at=NOW))
    db.add_all(
        [
            _prediction(peak_id, "acc", NOW),
            _prediction(peak_id, "acc", NOW - timedelta(days=3)),
            _prediction(peak_id, "anon", NOW),
        ]
    )
    await db.flush()

    await daily_stats.record_snapshot(db, NOW)

    row = await db.get(DailyStat, NOW.date())
    assert row is not None
    assert (row.users_total, row.accounts_total, row.checks) == (2, 1, 2)


async def test_record_snapshot_is_idempotent_and_updates_the_day(
    db: AsyncSession, peak_id: str
) -> None:
    await daily_stats.record_snapshot(db, NOW)
    db.add(_prediction(peak_id, "anon", NOW))
    await db.flush()
    await daily_stats.record_snapshot(db, NOW)

    rows = (await db.scalars(select(DailyStat))).all()
    assert len(rows) == 1
    assert (rows[0].users_total, rows[0].checks) == (1, 1)


async def test_snapshots_since_returns_rows_by_day(db: AsyncSession) -> None:
    db.add_all(
        DailyStat(day=NOW.date() - timedelta(days=n), users_total=n, accounts_total=0, checks=0)
        for n in (0, 3, 10)
    )
    await db.flush()

    rows = await daily_stats.snapshots_since(db, NOW.date() - timedelta(days=5))

    assert rows == {NOW.date(): 0, NOW.date() - timedelta(days=3): 3}
