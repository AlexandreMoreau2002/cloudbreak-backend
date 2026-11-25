import os
import asyncio
from uuid import uuid4
from pathlib import Path
from unittest.mock import patch
from collections.abc import Callable, Iterator

import pytest
from alembic import command
from sqlalchemy import DDL
from alembic.config import Config
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


async def _run_database_ddl(url: URL, operation: DDL) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(operation)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def postgresql_database_url() -> Iterator[URL]:
    configured_url = os.getenv("TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL instance for integration tests")

    admin_url = make_url(configured_url)
    database = f"cloudbreak_test_{uuid4().hex}"
    asyncio.run(_run_database_ddl(admin_url, DDL(f"CREATE DATABASE {database} TEMPLATE template0")))
    try:
        yield admin_url.set(database=database)
    finally:
        asyncio.run(_run_database_ddl(admin_url, DDL(f"DROP DATABASE {database} WITH (FORCE)")))


@pytest.fixture(scope="module")
def upgrade_postgresql(postgresql_database_url: URL) -> Callable[[str], None]:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))

    def upgrade(revision: str) -> None:
        with patch.object(
            settings, "database_url", postgresql_database_url.render_as_string(hide_password=False)
        ):
            command.upgrade(config, revision)

    return upgrade
