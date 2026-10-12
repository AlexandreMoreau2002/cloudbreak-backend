"""Tests du service d'envoi de notifications push (API Expo mockée)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.dialects import postgresql

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
        sent = await send_push_to_user(_user(), "Titre", "Corps", {"peak": "p1"})
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
        assert await send_push_to_user(_user(token=None), "t", "b") is False
        assert await send_push_to_user(_user(valid=False), "t", "b") is False
    client.post.assert_not_awaited()


def _session_maker(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=session)


def _device_not_registered() -> httpx.Response:
    return httpx.Response(
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


@pytest.mark.asyncio
async def test_device_not_registered_invalidates_token_in_dedicated_session() -> None:
    user = _user()
    session = MagicMock(execute=AsyncMock(), commit=AsyncMock())
    with (
        patch(
            "app.services.notifications.httpx.AsyncClient",
            return_value=_client(_device_not_registered()),
        ),
        patch("app.services.notifications.async_session_maker", _session_maker(session)),
    ):
        sent = await send_push_to_user(user, "t", "b")
    assert sent is False
    assert user.push_token_valid is True  # l'objet de l'appelant n'est pas touché
    session.commit.assert_awaited_once()
    compiled = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert str(compiled) == (
        "UPDATE users SET push_token_valid=%(push_token_valid)s "
        "WHERE users.supabase_user_id = %(supabase_user_id_1)s "
        "AND users.push_token = %(push_token_1)s"
    )
    assert compiled.params == {
        "push_token_valid": False,
        "supabase_user_id_1": "u1",
        "push_token_1": "ExponentPushToken[a]",
    }


@pytest.mark.asyncio
async def test_invalidation_failure_never_raises() -> None:
    session = MagicMock(execute=AsyncMock(side_effect=OSError("db down")), commit=AsyncMock())
    with (
        patch(
            "app.services.notifications.httpx.AsyncClient",
            return_value=_client(_device_not_registered()),
        ),
        patch("app.services.notifications.async_session_maker", _session_maker(session)),
    ):
        assert await send_push_to_user(_user(), "t", "b") is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_network_error_never_raises_and_keeps_token_valid() -> None:
    user = _user()
    with patch(
        "app.services.notifications.httpx.AsyncClient",
        return_value=_client(httpx.ConnectError("boom")),
    ):
        sent = await send_push_to_user(user, "t", "b")
    assert sent is False
    assert user.push_token_valid is True


@pytest.mark.asyncio
async def test_http_5xx_never_raises() -> None:
    response = httpx.Response(503, request=httpx.Request("POST", "http://x"))
    with patch("app.services.notifications.httpx.AsyncClient", return_value=_client(response)):
        assert await send_push_to_user(_user(), "t", "b") is False


@pytest.mark.asyncio
async def test_authorization_header_only_when_access_token_set() -> None:
    client = _client(_ok())
    with (
        patch("app.services.notifications.httpx.AsyncClient", return_value=client),
        patch("app.services.notifications.settings.expo_access_token", "secret"),
    ):
        await send_push_to_user(_user(), "t", "b")
    assert client.post.await_args.kwargs["headers"]["Authorization"] == "Bearer secret"


def _json_response(body: object) -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request("POST", "http://x"))


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"data": []}, {"data": "x"}, {"data": ["x"]}, "oops"])
async def test_unexpected_expo_body_never_raises(body: object) -> None:
    client = _client(_json_response(body))
    with patch("app.services.notifications.httpx.AsyncClient", return_value=client):
        assert await send_push_to_user(_user(), "t", "b") is False


@pytest.mark.asyncio
async def test_batch_response_uses_first_ticket() -> None:
    client = _client(_json_response({"data": [{"status": "ok", "id": "x"}]}))
    with patch("app.services.notifications.httpx.AsyncClient", return_value=client):
        assert await send_push_to_user(_user(), "t", "b") is True
