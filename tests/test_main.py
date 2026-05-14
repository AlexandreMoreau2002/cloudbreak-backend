import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from httpx import ASGITransport, AsyncClient
from app.main import app, db_operational_error_handler


def test_lifespan_startup() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_db_operational_error_handler_retourne_503() -> None:
    """OperationalError sur un endpoint → 503 + code DATABASE_UNAVAILABLE."""
    # On appelle le handler directement avec une vraie OperationalError
    exc = OperationalError("statement", {}, Exception("connection refused"))
    mock_request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/health",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
        }
    )
    response = await db_operational_error_handler(mock_request, exc)

    assert response.status_code == 503
    import json

    body = json.loads(response.body)
    assert body["detail"] == "Base de données indisponible"
    assert body["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_db_operational_error_handler_via_endpoint() -> None:
    """OperationalError levée dans un endpoint → handler global retourne 503."""
    from fastapi import APIRouter
    from sqlalchemy.exc import OperationalError as SAOperationalError

    test_router = APIRouter()

    @test_router.get("/_test_db_error")
    async def _trigger_db_error() -> None:
        raise SAOperationalError("stmt", {}, Exception("db down"))

    app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/_test_db_error")

    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "Base de données indisponible"
    assert body["code"] == "DATABASE_UNAVAILABLE"
