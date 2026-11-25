import asyncio
from collections.abc import Callable

from sqlalchemy import inspect
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


async def _columns(url: URL) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda conn: {c["name"] for c in inspect(conn).get_columns("daily_stats")}
            )
    finally:
        await engine.dispose()


def test_empty_postgresql_gains_daily_stats(
    postgresql_database_url: URL, upgrade_postgresql: Callable[[str], None]
) -> None:
    upgrade_postgresql("head")
    assert asyncio.run(_columns(postgresql_database_url)) == {
        "day",
        "users_total",
        "accounts_total",
        "checks",
    }
