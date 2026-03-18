import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import Base, get_db, async_session_maker


def test_base_declarative() -> None:
    assert Base is not None
    assert hasattr(Base, "metadata")


def test_async_session_maker() -> None:
    assert async_session_maker is not None


@pytest.mark.asyncio
async def test_get_db_yields_session() -> None:
    gen = get_db()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    await session.close()
