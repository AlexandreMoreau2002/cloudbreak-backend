import sys
import subprocess
from textwrap import dedent
from unittest.mock import patch

from app.core.sentry import initialize_sentry


def test_empty_dsn_does_not_initialize_sentry() -> None:
    with patch("app.core.sentry.sentry_sdk.init") as sdk_init:
        initialize_sentry("", "development", "1.0.0")

    sdk_init.assert_not_called()


def test_configured_dsn_initializes_sentry_for_errors_with_privacy_options() -> None:
    with patch("app.core.sentry.sentry_sdk.init") as sdk_init:
        initialize_sentry("https://example.invalid/1", "production", "1.0.0")

    sdk_init.assert_called_once()
    options = sdk_init.call_args.kwargs
    assert options["dsn"] == "https://example.invalid/1"
    assert options["environment"] == "production"
    assert options["release"] == "1.0.0"
    assert options["send_default_pii"] is False
    assert options["max_request_body_size"] == "never"
    assert options["include_local_variables"] is False
    assert options["max_breadcrumbs"] == 0
    assert options["traces_sample_rate"] is None
    assert options["profile_session_sample_rate"] == 0.0
    assert options["auto_session_tracking"] is False
    assert [integration.identifier for integration in options["disabled_integrations"]] == [
        "logging"
    ]


def test_sentry_keeps_exception_type_and_stack_without_request_or_error_values() -> None:
    with patch("app.core.sentry.sentry_sdk.init") as sdk_init:
        initialize_sentry("https://example.invalid/1", "production", "1.0.0")

    before_send = sdk_init.call_args.kwargs["before_send"]
    stacktrace = {"frames": [{"filename": "score.py", "function": "get_score", "lineno": 42}]}
    event = {
        "request": {
            "url": "https://example.invalid/score",
            "method": "POST",
            "query_string": "lat=45.123456&lon=6.123456",
            "headers": {"Authorization": "Bearer example-token"},
            "data": {"email": "client@example.invalid"},
            "cookies": {"session": "example-token"},
        },
        "user": {"email": "client@example.invalid"},
        "breadcrumbs": {"values": [{"message": "lat=45.123456&lon=6.123456"}]},
        "extra": {"token": "example-token"},
        "logentry": {"formatted": "Request from client@example.invalid"},
        "exception": {
            "values": [
                {"type": "ValueError", "value": "token example-token", "stacktrace": stacktrace},
                {"type": "RuntimeError", "value": "email client@example.invalid"},
            ]
        },
        "environment": "production",
        "release": "1.0.0",
    }

    assert before_send(event, {}) == {
        "environment": "production",
        "release": "1.0.0",
        "exception": {
            "values": [{"type": "ValueError", "stacktrace": stacktrace}, {"type": "RuntimeError"}]
        },
    }


def test_fastapi_does_not_send_incoming_sentry_baggage() -> None:
    # Sentry patches FastAPI and Starlette globally, so exercise the real SDK in a fresh process.
    script = dedent("""
        import asyncio
        from unittest.mock import patch

        import sentry_sdk
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
        from sentry_sdk.transport import Transport

        from app.core.sentry import initialize_sentry

        envelopes = []
        upstream_requests = []

        class MemoryTransport(Transport):
            def capture_envelope(self, envelope):
                envelopes.append(envelope)

        real_init = sentry_sdk.init
        with patch.object(
            sentry_sdk, "init", side_effect=lambda **options: real_init(
                transport=MemoryTransport, **options
            )
        ):
            initialize_sentry("https://test@example.invalid/1", "development", "1.0.0")

        app = FastAPI()

        def upstream(request):
            upstream_requests.append(request)
            return Response(200)

        @app.get("/failure")
        async def failure():
            async with AsyncClient(transport=MockTransport(upstream)) as client:
                await client.get("https://api.vendor.invalid")
            raise ValueError("controlled error")

        # Bypass HTTPX client instrumentation so the incoming headers reach the ASGI boundary.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        request = Request("GET", "http://testserver/failure", headers={
            "sentry-trace": "12345678901234567890123456789012-1234567890123456-1",
            "baggage": "sentry-transaction=client%40example.invalid,sentry-token=synthetic-token",
        })
        response = asyncio.run(transport.handle_async_request(request))

        assert response.status_code == 500
        [upstream_request] = upstream_requests
        leaked_headers = {
            name: upstream_request.headers[name]
            for name in ("sentry-trace", "baggage")
            if name in upstream_request.headers
        }
        assert not leaked_headers, leaked_headers
        [envelope] = envelopes
        [item] = envelope.items
        assert item.type == "event"
        assert item.payload.json["exception"]["values"][-1]["type"] == "ValueError"
        assert "trace" not in envelope.headers, envelope.headers
        serialized = envelope.serialize()
        assert b"client@example.invalid" not in serialized
        assert b"synthetic-token" not in serialized
        """)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
