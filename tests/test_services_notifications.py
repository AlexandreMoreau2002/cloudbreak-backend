"""Tests du service d'envoi de notifications push (API Expo mockée)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.notifications import send_push_to_user


def _user(token: str | None = "ExponentPushToken[a]", valid: bool = True):
    return SimpleNamespace(supabase_user_id="u1", push_token=token, push_token_valid=valid)


def _client(response: httpx.Response | Exception) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    if isinstance(response, Exception):
        client.post = AsyncMock(side_effect=response)
    else:
        client.post = AsyncMock(return_value=response)
    return client


def _ok() -> httpx.Response:
    return httpx.Response(
        200, json={"data": {"status": "ok", "id": "x"}}, request=httpx.Request("POST", "http://x")
    )


@pytest.mark.asyncio
async def test_sends_payload_to_expo_and_returns_true() -> None:
    client = _client(_ok())
    with patch("app.services.notifications.httpx.AsyncClient", return_value=client):
        sent = await send_push_to_user(AsyncMock(), _user(), "Titre", "Corps", {"peak": "p1"})
    assert sent is True
    payload = client.post.await_args.kwargs["json"]
    assert payload["to"] == "ExponentPushToken[a]"
    assert payload["title"] == "Titre"
    assert payload["body"] == "Corps"
    assert payload["data"] == {"peak": "p1"}


@pytest.mark.asyncio
async def test_skips_user_without_valid_token() -> None:
    client = _client(_ok())
    with patch("app.services.notifications.httpx.AsyncClient", return_value=client):
        assert await send_push_to_user(AsyncMock(), _user(token=None), "t", "b") is False
        assert await send_push_to_user(AsyncMock(), _user(valid=False), "t", "b") is False
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_not_registered_marks_token_invalid() -> None:
    response = httpx.Response(
        200,
        json={
            "data": {
                "status": "error",
                "message": "gone",
                "details": {"error": "DeviceNotRegistered"},
            }
        },
        request=httpx.Request("POST", "http://x"),
    )
    user = _user()
    db = AsyncMock()
    with patch("app.services.notifications.httpx.AsyncClient", return_value=_client(response)):
        sent = await send_push_to_user(db, user, "t", "b")
    assert sent is False
    assert user.push_token_valid is False
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_network_error_never_raises_and_keeps_token_valid() -> None:
    user = _user()
    with patch(
        "app.services.notifications.httpx.AsyncClient",
        return_value=_client(httpx.ConnectError("boom")),
    ):
        sent = await send_push_to_user(AsyncMock(), user, "t", "b")
    assert sent is False
    assert user.push_token_valid is True


@pytest.mark.asyncio
async def test_http_5xx_never_raises() -> None:
    response = httpx.Response(503, request=httpx.Request("POST", "http://x"))
    with patch("app.services.notifications.httpx.AsyncClient", return_value=_client(response)):
        assert await send_push_to_user(AsyncMock(), _user(), "t", "b") is False


@pytest.mark.asyncio
async def test_authorization_header_only_when_access_token_set() -> None:
    client = _client(_ok())
    with (
        patch("app.services.notifications.httpx.AsyncClient", return_value=client),
        patch("app.services.notifications.settings.expo_access_token", "secret"),
    ):
        await send_push_to_user(AsyncMock(), _user(), "t", "b")
    assert client.post.await_args.kwargs["headers"]["Authorization"] == "Bearer secret"


def _json_response(body: object) -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request("POST", "http://x"))


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"data": []}, {"data": "x"}, {"data": ["x"]}, "oops"])
async def test_unexpected_expo_body_never_raises(body: object) -> None:
    client = _client(_json_response(body))
    with patch("app.services.notifications.httpx.AsyncClient", return_value=client):
        assert await send_push_to_user(AsyncMock(), _user(), "t", "b") is False


@pytest.mark.asyncio
async def test_batch_response_uses_first_ticket() -> None:
    client = _client(_json_response({"data": [{"status": "ok", "id": "x"}]}))
    with patch("app.services.notifications.httpx.AsyncClient", return_value=client):
        assert await send_push_to_user(AsyncMock(), _user(), "t", "b") is True
