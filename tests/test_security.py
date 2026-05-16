import json
import time
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from jose import jwt
from jose.backends import ECKey
from fastapi import HTTPException
from app.core.errors import ErrorCode
from tests.helpers import encode_test_jwt
from app.core.security import decode_supabase_jwt, delete_supabase_user

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
    }
    token = _make_token(payload)
    result = decode_supabase_jwt(token, json.dumps(TEST_PUBLIC_JWK))
    assert result["sub"] == "user-123"
    assert result["email"] == "test@cloudbreak.app"


def test_decode_invalid_token() -> None:
    with pytest.raises(ValueError):
        decode_supabase_jwt("not.a.valid.token", json.dumps(TEST_PUBLIC_JWK))


def test_decode_expired_token() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) - 3600,
    }
    token = _make_token(payload)
    with pytest.raises(ValueError):
        decode_supabase_jwt(token, json.dumps(TEST_PUBLIC_JWK))


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
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


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
