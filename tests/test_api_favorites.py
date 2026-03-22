"""
Tests des endpoints favoris :
  POST   /api/v1/user/favorites
  DELETE /api/v1/user/favorites/{peak_id}
  GET    /api/v1/user/favorites

On mocke la DB et l'auth.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


MOCK_USER = {"id": "user-123", "email": "alex@test.com"}

MOCK_PEAK = MagicMock()
MOCK_PEAK.id = "peak-1"
MOCK_PEAK.name = "Mont Blanc"
MOCK_PEAK.slug = "mont-blanc"
MOCK_PEAK.lat = 45.83
MOCK_PEAK.lng = 6.86
MOCK_PEAK.altitude = 4808

MOCK_FAV_ID = uuid.uuid4()
MOCK_CREATED_AT = datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC)

MOCK_FAV = MagicMock()
MOCK_FAV.id = MOCK_FAV_ID
MOCK_FAV.user_id = "user-123"
MOCK_FAV.peak_id = "peak-1"
MOCK_FAV.created_at = MOCK_CREATED_AT


@pytest.fixture
def auth_override():
    from app.core.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    yield
    app.dependency_overrides.clear()


def _make_db_mock() -> AsyncMock:
    """DB mock de base avec add/commit/refresh en no-op."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.delete = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# POST /api/v1/user/favorites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_favorite_retourne_201(auth_override: None) -> None:
    """Ajout favori valide → 201 avec peak info."""
    from app.db.session import get_db

    mock_db = _make_db_mock()

    # 1er execute → trouver peak, 2ème → vérifier doublon (aucun)
    peak_result = MagicMock()
    peak_result.scalar_one_or_none.return_value = MOCK_PEAK
    no_dup_result = MagicMock()
    no_dup_result.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(side_effect=[peak_result, no_dup_result])
    mock_db.refresh = AsyncMock(
        side_effect=lambda fav: (
            setattr(fav, "created_at", MOCK_CREATED_AT) or setattr(fav, "id", MOCK_FAV_ID)
        )
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/user/favorites", json={"peak_id": "peak-1"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 201
    data = response.json()
    assert data["peak_id"] == "peak-1"
    assert data["peak"]["name"] == "Mont Blanc"


@pytest.mark.asyncio
async def test_add_favorite_doublon_retourne_409(auth_override: None) -> None:
    """Ajout d'un favori déjà existant → 409 ALREADY_EXISTS."""
    from app.db.session import get_db

    mock_db = _make_db_mock()

    peak_result = MagicMock()
    peak_result.scalar_one_or_none.return_value = MOCK_PEAK
    dup_result = MagicMock()
    dup_result.scalar_one_or_none.return_value = MOCK_FAV  # doublon

    mock_db.execute = AsyncMock(side_effect=[peak_result, dup_result])

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/user/favorites", json={"peak_id": "peak-1"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_add_favorite_peak_inexistant_retourne_404(auth_override: None) -> None:
    """Peak inconnu → 404 PEAK_NOT_FOUND."""
    from app.db.session import get_db

    mock_db = _make_db_mock()
    not_found_result = MagicMock()
    not_found_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=not_found_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/user/favorites", json={"peak_id": "inexistant"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PEAK_NOT_FOUND"


@pytest.mark.asyncio
async def test_add_favorite_sans_jwt_retourne_403() -> None:
    """Sans Authorization → 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/user/favorites", json={"peak_id": "peak-1"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/v1/user/favorites/{peak_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_favorite_retourne_204(auth_override: None) -> None:
    """Suppression favori existant → 204."""
    from app.db.session import get_db

    mock_db = _make_db_mock()
    fav_result = MagicMock()
    fav_result.scalar_one_or_none.return_value = MOCK_FAV
    mock_db.execute = AsyncMock(return_value=fav_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete("/api/v1/user/favorites/peak-1")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_remove_favorite_inexistant_retourne_404(auth_override: None) -> None:
    """Favori introuvable → 404 NOT_FOUND."""
    from app.db.session import get_db

    mock_db = _make_db_mock()
    not_found_result = MagicMock()
    not_found_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=not_found_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete("/api/v1/user/favorites/peak-1")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /api/v1/user/favorites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_favorites_retourne_200(auth_override: None) -> None:
    """Listage des favoris → 200 avec peak info."""
    from app.db.session import get_db

    mock_db = _make_db_mock()
    list_result = MagicMock()
    list_result.all.return_value = [(MOCK_FAV, MOCK_PEAK)]
    mock_db.execute = AsyncMock(return_value=list_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/user/favorites")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["peak"]["name"] == "Mont Blanc"
    assert data[0]["peak_id"] == "peak-1"


@pytest.mark.asyncio
async def test_list_favorites_sans_jwt_retourne_403() -> None:
    """Sans Authorization → 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/user/favorites")
    assert response.status_code == 403
