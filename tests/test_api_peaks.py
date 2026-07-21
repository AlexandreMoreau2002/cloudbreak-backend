"""
Tests de l'endpoint GET /api/v1/peaks/search et GET /api/v1/peaks/{slug}

Ces endpoints sont publics depuis la story 7.1 (onboarding mobile pré-login) :
aucune authentification requise.

On mocke :
- La DB (execute)
"""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app


MOCK_PEAK = MagicMock()
MOCK_PEAK.id = "peak-1"
MOCK_PEAK.name = "Mont Blanc"
MOCK_PEAK.slug = "mont-blanc"
MOCK_PEAK.lat = 45.83
MOCK_PEAK.lng = 6.86
MOCK_PEAK.altitude = 4808
MOCK_PEAK.region = "Massif du Mont-Blanc"


@pytest.fixture
def db_override_search():
    """DB mock qui retourne une liste contenant MOCK_PEAK."""
    from app.db.session import get_db

    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [MOCK_PEAK]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def db_override_empty():
    """DB mock qui retourne une liste vide."""
    from app.db.session import get_db

    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def db_override_peak_detail():
    """DB mock qui retourne MOCK_PEAK via scalar_one_or_none."""
    from app.db.session import get_db

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MOCK_PEAK
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def db_override_peak_not_found():
    """DB mock qui retourne None."""
    from app.db.session import get_db

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /api/v1/peaks/search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_retourne_200_avec_resultats(db_override_search: None) -> None:
    """Recherche valide → 200 avec liste de peaks.

    Endpoint public depuis story 7.1 (onboarding pré-login) — aucune auth requise :
    la requête est envoyée sans header Authorization.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/peaks/search", params={"q": "mont"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "Mont Blanc"
    assert data[0]["altitude"] == 4808
    assert data[0]["region"] == "Massif du Mont-Blanc"
    assert "id" in data[0]
    assert "slug" in data[0]


@pytest.mark.asyncio
async def test_search_retourne_liste_vide(db_override_empty: None) -> None:
    """Aucun résultat → 200 avec liste vide."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/peaks/search", params={"q": "zzz"})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_q_trop_court_retourne_422() -> None:
    """q < 2 chars → 422 Unprocessable Entity."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/peaks/search", params={"q": "m"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/peaks/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peak_detail_retourne_200(db_override_peak_detail: None) -> None:
    """Slug existant → 200 avec tous les champs.

    Endpoint public depuis story 7.1 (onboarding pré-login) — aucune auth requise :
    la requête est envoyée sans header Authorization.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/peaks/mont-blanc")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Mont Blanc"
    assert data["slug"] == "mont-blanc"
    assert data["altitude"] == 4808
    assert data["region"] == "Massif du Mont-Blanc"
    assert "lat" in data
    assert "lng" in data


@pytest.mark.asyncio
async def test_peak_detail_slug_inexistant_retourne_404(
    db_override_peak_not_found: None,
) -> None:
    """Slug inconnu → 404 PEAK_NOT_FOUND."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/peaks/inexistant")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PEAK_NOT_FOUND"
