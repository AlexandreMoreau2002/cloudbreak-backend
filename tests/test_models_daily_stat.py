from collections.abc import AsyncIterator, Callable
from datetime import date

import pytest
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.daily_stat import DailyStat


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


def test_daily_stat_has_no_personal_fields() -> None:
    assert set(DailyStat.__table__.columns.keys()) == {
        "day",
        "users_total",
        "accounts_total",
        "checks",
    }


async def test_daily_stat_roundtrip(db: AsyncSession) -> None:
    day = date(2026, 11, 25)
    db.add(DailyStat(day=day, users_total=3, accounts_total=1, checks=7))
    await db.flush()
    db.expunge_all()

    row = await db.get(DailyStat, day)

    assert row is not None
    assert (row.users_total, row.accounts_total, row.checks) == (3, 1, 7)
