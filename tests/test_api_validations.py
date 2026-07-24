"""
Tests de l'endpoint POST /api/v1/validations.

On mocke la DB et l'auth, même pattern que test_api_favorites.py.
"""

import uuid
import pytest
from datetime import UTC, datetime
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app


MOCK_USER = {"id": "user-123", "email": "alex@test.com"}
MOCK_PREDICTION_ID = uuid.uuid4()
MOCK_VALIDATION_ID = uuid.uuid4()
MOCK_VALIDATED_AT = datetime(2026, 7, 24, 10, 0, 0, tzinfo=UTC)

MOCK_PREDICTION = MagicMock()
MOCK_PREDICTION.id = MOCK_PREDICTION_ID


@pytest.fixture
def auth_override():
    from app.core.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    yield
    app.dependency_overrides.clear()


def _make_db_mock() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


@pytest.mark.asyncio
async def test_post_validation_retourne_201(auth_override: None) -> None:
    """Validation avec prediction_id existant → 201."""
    from app.db.session import get_db

    mock_db = _make_db_mock()
    pred_result = MagicMock()
    pred_result.scalar_one_or_none.return_value = MOCK_PREDICTION
    mock_db.execute = AsyncMock(return_value=pred_result)
    mock_db.refresh = AsyncMock(
        side_effect=lambda v: (
            setattr(v, "id", MOCK_VALIDATION_ID) or setattr(v, "validated_at", MOCK_VALIDATED_AT)
        )
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/validations",
                json={
                    "prediction_id": str(MOCK_PREDICTION_ID),
                    "result": True,
                    "lat": 45.83,
                    "lng": 6.86,
                },
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 201
    body = response.json()
    assert body["result"] is True
    assert body["user_id"] == "user-123"
    assert body["photo_url"] is None
    assert mock_db.add.called


@pytest.mark.asyncio
async def test_post_validation_result_false(auth_override: None) -> None:
    """Validation avec result: false → enregistré tel quel."""
    from app.db.session import get_db

    mock_db = _make_db_mock()
    pred_result = MagicMock()
    pred_result.scalar_one_or_none.return_value = MOCK_PREDICTION
    mock_db.execute = AsyncMock(return_value=pred_result)
    mock_db.refresh = AsyncMock(
        side_effect=lambda v: (
            setattr(v, "id", MOCK_VALIDATION_ID) or setattr(v, "validated_at", MOCK_VALIDATED_AT)
        )
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/validations",
                json={"prediction_id": str(MOCK_PREDICTION_ID), "result": False},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 201
    assert response.json()["result"] is False


@pytest.mark.asyncio
async def test_post_validation_sans_jwt_retourne_403() -> None:
    """Pas de JWT → 403 (HTTPBearer, même comportement que favorites)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/validations",
            json={"prediction_id": str(MOCK_PREDICTION_ID), "result": True},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_validation_prediction_inconnue_retourne_404(auth_override: None) -> None:
    """prediction_id inconnu → 404."""
    from app.db.session import get_db

    mock_db = _make_db_mock()
    pred_result = MagicMock()
    pred_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=pred_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/validations",
                json={"prediction_id": str(uuid.uuid4()), "result": True},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_validation_prediction_dune_autre_utilisateur_retourne_404(
    auth_override: None,
) -> None:
    """prediction_id existant mais appartenant à un autre utilisateur → 404 (pas 403).

    La query filtre désormais sur Prediction.user_id == current_user["id"], donc une
    prédiction d'un autre utilisateur ne remonte jamais (scalar_one_or_none() -> None),
    exactement comme une prédiction inexistante.
    """
    from app.db.session import get_db

    mock_db = _make_db_mock()
    pred_result = MagicMock()
    pred_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=pred_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/validations",
                json={"prediction_id": str(MOCK_PREDICTION_ID), "result": True},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_post_validation_payload_invalide_retourne_422(auth_override: None) -> None:
    """result manquant → 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/validations",
            json={"prediction_id": str(MOCK_PREDICTION_ID)},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_validation_prediction_id_malformee_retourne_422(auth_override: None) -> None:
    """prediction_id qui n'est pas un UUID valide → 422 (jamais de 500 DB)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/validations",
            json={"prediction_id": "not-a-uuid", "result": True},
        )
    assert response.status_code == 422
