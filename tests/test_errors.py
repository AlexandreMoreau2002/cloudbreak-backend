import json
import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.errors import ApiError, ErrorCode, log_server_error


def test_error_codes_are_stable_strings() -> None:
    assert ErrorCode.QUOTA_EXCEEDED == "QUOTA_EXCEEDED"
    assert ErrorCode.PEAK_NOT_FOUND == "PEAK_NOT_FOUND"
    assert ErrorCode.WEATHER_UNAVAILABLE == "WEATHER_UNAVAILABLE"
    assert ErrorCode.INVALID_TOKEN == "INVALID_TOKEN"


def test_error_codes_do_not_duplicate_values() -> None:
    values = [
        ErrorCode.QUOTA_EXCEEDED,
        ErrorCode.PEAK_NOT_FOUND,
        ErrorCode.WEATHER_UNAVAILABLE,
        ErrorCode.SUBSCRIPTION_REQUIRED,
        ErrorCode.INVALID_TOKEN,
        ErrorCode.TOKEN_EXPIRED,
        ErrorCode.NOT_FOUND,
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.ALREADY_EXISTS,
    ]

    assert len(values) == len(set(values))


def _json_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.levelno >= logging.ERROR]


def test_log_server_error_emet_un_json_structure(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        log_server_error("/api/v1/score", 500, RuntimeError("secret=abc"))

    assert _json_records(caplog) == [
        {"level": "error", "path": "/api/v1/score", "status": 500, "error": "RuntimeError"}
    ]


def test_erreur_non_geree_est_loggee_en_json_sans_stack_ni_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = create_app("production")

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("password=hunter2")

    with caplog.at_level(logging.ERROR):
        response = TestClient(application, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Erreur interne", "code": "INTERNAL_ERROR"}
    records = _json_records(caplog)
    assert records == [{"level": "error", "path": "/boom", "status": 500, "error": "RuntimeError"}]
    assert all(r.exc_info is None for r in caplog.records)
    assert "hunter2" not in caplog.text


def test_api_error_5xx_est_loggee_mais_pas_4xx(caplog: pytest.LogCaptureFixture) -> None:
    application = create_app("production")

    @application.get("/unavailable")
    async def unavailable() -> None:
        raise ApiError(503, "Indisponible", ErrorCode.SERVICE_UNAVAILABLE)

    @application.get("/missing")
    async def missing() -> None:
        raise ApiError(404, "Absent", ErrorCode.NOT_FOUND)

    client = TestClient(application, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        assert client.get("/missing").status_code == 404
        assert client.get("/unavailable").status_code == 503

    assert _json_records(caplog) == [
        {"level": "error", "path": "/unavailable", "status": 503, "error": "ApiError"}
    ]


def test_http_exception_5xx_est_loggee(caplog: pytest.LogCaptureFixture) -> None:
    application = create_app("production")

    @application.get("/bad-gateway")
    async def bad_gateway() -> None:
        raise HTTPException(status_code=502, detail="upstream")

    with caplog.at_level(logging.ERROR):
        response = TestClient(application, raise_server_exceptions=False).get("/bad-gateway")

    assert response.status_code == 502
    assert _json_records(caplog) == [
        {"level": "error", "path": "/bad-gateway", "status": 502, "error": "HTTPException"}
    ]
