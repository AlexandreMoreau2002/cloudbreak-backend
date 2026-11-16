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
