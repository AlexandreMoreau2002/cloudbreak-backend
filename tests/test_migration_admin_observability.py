import asyncio
from collections.abc import Callable

from sqlalchemy import inspect
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


async def _tables(url: URL) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
    finally:
        await engine.dispose()


def test_empty_postgresql_gains_admin_tables_at_revision_c3d4e5f6a7b8(
    postgresql_database_url: URL, upgrade_postgresql: Callable[[str], None]
) -> None:
    assert asyncio.run(_tables(postgresql_database_url)) == set()
    upgrade_postgresql("b7c8d9e0f1a2")
    before = asyncio.run(_tables(postgresql_database_url))
    assert {"alembic_version", "users", "predictions", "subscriptions"} <= before
    admin_tables = {"admin_audit_log", "cron_heartbeats"}
    assert before.isdisjoint(admin_tables)

    upgrade_postgresql("c3d4e5f6a7b8")

    assert asyncio.run(_tables(postgresql_database_url)) == before | admin_tables
