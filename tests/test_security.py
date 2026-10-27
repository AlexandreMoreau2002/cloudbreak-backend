import json
import time
import httpx
import pytest
from jose import jwt
from typing import Any
from jose.backends import ECKey
from fastapi import HTTPException
from unittest.mock import AsyncMock
from app.core.errors import ErrorCode
from tests.helpers import encode_test_jwt
from app.core.security import (
    SupabaseAdminError,
    get_supabase_user,
    decode_supabase_jwt,
    delete_supabase_user,
)

# Paire de clés ECC P-256 éphémère — tests uniquement
TEST_PRIVATE_JWK = {
    "x": "HGpCklI-j-RfFtZ2jYiGQuNvFzI27vthKfHjn8YRc8A",
    "y": "YQByzZt-ZOdAiAuzJIypZSY1slIjBZvViba1It2b9B8",
    "d": "_cK_OmehRWDsNLRPavguz6Dj9GV7Yf1IOWzD3C8QG-Y",
    "kty": "EC",
    "crv": "P-256",
    "alg": "ES256",
    "kid": "test-key",
}

TEST_PUBLIC_JWK = {k: v for k, v in TEST_PRIVATE_JWK.items() if k != "d"}


def _make_token(payload: dict) -> str:
    private_key = ECKey(TEST_PRIVATE_JWK, algorithm="ES256")
    return jwt.encode(payload, private_key, algorithm="ES256")


def test_decode_valid_token() -> None:
    payload = {
        "sub": "user-123",
        "email": "test@cloudbreak.app",
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
        "iss": "https://test.supabase.co/auth/v1",
    }
    token = _make_token(payload)
    result = decode_supabase_jwt(
        token,
        json.dumps(TEST_PUBLIC_JWK),
        supabase_url="https://test.supabase.co",
    )
    assert result["sub"] == "user-123"
    assert result["email"] == "test@cloudbreak.app"


def test_decode_rejects_wrong_audience() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) + 3600,
        "aud": "some-other-audience",
        "iss": "https://test.supabase.co/auth/v1",
    }
    token = _make_token(payload)
    with pytest.raises(ValueError):
        decode_supabase_jwt(
            token,
            json.dumps(TEST_PUBLIC_JWK),
            supabase_url="https://test.supabase.co",
        )


def test_decode_rejects_wrong_issuer() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
        "iss": "https://attacker.supabase.co/auth/v1",
    }
    token = _make_token(payload)
    with pytest.raises(ValueError):
        decode_supabase_jwt(
            token,
            json.dumps(TEST_PUBLIC_JWK),
            supabase_url="https://test.supabase.co",
        )


def test_decode_rejects_missing_issuer() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
    }
    token = _make_token(payload)
    with pytest.raises(ValueError):
        decode_supabase_jwt(
            token,
            json.dumps(TEST_PUBLIC_JWK),
            supabase_url="https://test.supabase.co",
        )


def test_decode_rejects_missing_audience() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) + 3600,
        "iss": "https://test.supabase.co/auth/v1",
    }
    token = _make_token(payload)
    with pytest.raises(ValueError):
        decode_supabase_jwt(
            token,
            json.dumps(TEST_PUBLIC_JWK),
            supabase_url="https://test.supabase.co",
        )


def test_decode_invalid_token() -> None:
    with pytest.raises(ValueError):
        decode_supabase_jwt(
            "not.a.valid.token",
            json.dumps(TEST_PUBLIC_JWK),
            supabase_url="https://test.supabase.co",
        )


def test_decode_expired_token() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) - 3600,
        "aud": "authenticated",
        "iss": "https://test.supabase.co/auth/v1",
    }
    token = _make_token(payload)
    with pytest.raises(ValueError):
        decode_supabase_jwt(
            token,
            json.dumps(TEST_PUBLIC_JWK),
            supabase_url="https://test.supabase.co",
        )


def test_decode_accepts_trailing_slash_in_supabase_url() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
        "iss": "https://test.supabase.co/auth/v1",
    }
    token = _make_token(payload)
    result = decode_supabase_jwt(
        token,
        json.dumps(TEST_PUBLIC_JWK),
        supabase_url="https://test.supabase.co/",
    )
    assert result["sub"] == "user-123"


def test_encode_test_jwt_signs_payload_with_dev_secret() -> None:
    payload = {"sub": "user-123", "email": "test@cloudbreak.app", "exp": int(time.time()) + 3600}

    token = encode_test_jwt(payload)
    decoded = jwt.decode(
        token,
        "dev-secret-key-very-insecure-do-not-use-in-prod",
        algorithms=["HS256"],
    )

    assert decoded["sub"] == "user-123"
    assert decoded["email"] == "test@cloudbreak.app"


class _FakeResponse:
    def __init__(self, status_code: int, body: Any = None, *, invalid_json: bool = False) -> None:
        self.status_code = status_code
        self._body = body
        self._invalid_json = invalid_json

    def json(self) -> Any:
        if self._invalid_json:
            raise ValueError("not json")
        return self._body


def _install_async_client(monkeypatch: pytest.MonkeyPatch, delete_mock: AsyncMock) -> None:
    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def delete(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            return await delete_mock(*args, **kwargs)

    monkeypatch.setattr("app.core.security.httpx.AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 204])
async def test_delete_supabase_user_accepts_success_statuses(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    delete_mock = AsyncMock(return_value=_FakeResponse(status_code))
    _install_async_client(monkeypatch, delete_mock)

    await delete_supabase_user(
        user_id="user-123",
        supabase_url="https://supabase.test",
        service_role_key="service-role",
    )

    delete_mock.assert_awaited_once_with(
        "https://supabase.test/auth/v1/admin/users/user-123",
        headers={
            "apikey": "service-role",
            "Authorization": "Bearer service-role",
        },
    )


@pytest.mark.asyncio
async def test_delete_supabase_user_timeout_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_mock = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    _install_async_client(monkeypatch, delete_mock)

    with pytest.raises(HTTPException) as exc_info:
        await delete_supabase_user(
            user_id="user-123",
            supabase_url="https://supabase.test",
            service_role_key="service-role",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "detail": "Timeout suppression compte Supabase",
        "code": ErrorCode.SERVICE_UNAVAILABLE,
    }


@pytest.mark.asyncio
async def test_delete_supabase_user_error_status_returns_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_mock = AsyncMock(return_value=_FakeResponse(500))
    _install_async_client(monkeypatch, delete_mock)

    with pytest.raises(HTTPException) as exc_info:
        await delete_supabase_user(
            user_id="user-123",
            supabase_url="https://supabase.test",
            service_role_key="service-role",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {
        "detail": "Erreur suppression compte",
        "code": ErrorCode.INTERNAL_ERROR,
    }


_USER_NOT_FOUND = {"code": 404, "error_code": "user_not_found", "msg": "User not found"}


async def _delete_with(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> None:
    _install_async_client(monkeypatch, AsyncMock(return_value=response))
    await delete_supabase_user(
        user_id="user-123",
        supabase_url="https://supabase.test",
        service_role_key="service-role",
    )


@pytest.mark.asyncio
async def test_delete_supabase_user_404_user_not_found_is_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _delete_with(monkeypatch, _FakeResponse(404, _USER_NOT_FOUND))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(404, invalid_json=True),
        _FakeResponse(404, {"code": 404, "msg": "Not found"}),
        _FakeResponse(404, {"error_code": "other"}),
        _FakeResponse(404, ["user_not_found"]),
    ],
)
async def test_delete_supabase_user_404_without_marker_returns_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    response: _FakeResponse,
) -> None:
    with caplog.at_level("WARNING"), pytest.raises(HTTPException) as exc_info:
        await _delete_with(monkeypatch, response)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {
        "detail": "Erreur suppression compte",
        "code": ErrorCode.INTERNAL_ERROR,
    }
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert "user-123" not in caplog.text
    assert "service-role" not in caplog.text


def _install_get_client(monkeypatch: pytest.MonkeyPatch, get_mock: AsyncMock) -> None:
    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            return await get_mock(*args, **kwargs)

    monkeypatch.setattr("app.core.security.httpx.AsyncClient", _FakeAsyncClient)


async def _get_with(monkeypatch: pytest.MonkeyPatch, get_mock: AsyncMock) -> object:
    _install_get_client(monkeypatch, get_mock)
    return await get_supabase_user(
        user_id="user-123",
        supabase_url="https://supabase.test",
        service_role_key="service-role",
    )


@pytest.mark.asyncio
async def test_get_supabase_user_200_returns_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"id": "user-123", "is_anonymous": True}
    get_mock = AsyncMock(return_value=_FakeResponse(200, body))

    result = await _get_with(monkeypatch, get_mock)

    assert result == body
    get_mock.assert_awaited_once_with(
        "https://supabase.test/auth/v1/admin/users/user-123",
        headers={"apikey": "service-role", "Authorization": "Bearer service-role"},
    )


@pytest.mark.asyncio
async def test_get_supabase_user_404_user_not_found_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _get_with(
        monkeypatch, AsyncMock(return_value=_FakeResponse(404, _USER_NOT_FOUND))
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(404, invalid_json=True),
        _FakeResponse(404, {"code": 404, "msg": "Not found"}),
        _FakeResponse(500, {"msg": "boom"}),
        _FakeResponse(401, {"msg": "bad key"}),
        _FakeResponse(200, invalid_json=True),
        _FakeResponse(200, ["not", "a", "dict"]),
    ],
)
async def test_get_supabase_user_unexpected_response_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    response: _FakeResponse,
) -> None:
    with caplog.at_level("DEBUG"), pytest.raises(SupabaseAdminError):
        await _get_with(monkeypatch, AsyncMock(return_value=response))

    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert "user-123" not in caplog.text
    assert "service-role" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response", [_FakeResponse(200, invalid_json=True), _FakeResponse(200, ["x"])]
)
async def test_get_supabase_user_invalid_200_body_has_a_distinct_message(
    monkeypatch: pytest.MonkeyPatch, response: _FakeResponse
) -> None:
    with pytest.raises(SupabaseAdminError, match="unexpected body for status 200"):
        await _get_with(monkeypatch, AsyncMock(return_value=response))


@pytest.mark.asyncio
async def test_get_supabase_user_network_error_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    get_mock = AsyncMock(side_effect=httpx.ConnectError("down"))

    with caplog.at_level("DEBUG"), pytest.raises(SupabaseAdminError):
        await _get_with(monkeypatch, get_mock)

    assert "user-123" not in caplog.text
    assert "service-role" not in caplog.text
