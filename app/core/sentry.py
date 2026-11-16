import sentry_sdk
from sentry_sdk.types import Event, Hint
from sentry_sdk.integrations.logging import LoggingIntegration


def _strip_sensitive_data(event: Event, _hint: Hint) -> Event:
    # Request data and exception messages can contain tokens, e-mail addresses or coordinates.
    event.pop("request", None)
    event.pop("user", None)
    event.pop("breadcrumbs", None)
    event.pop("extra", None)
    event.pop("logentry", None)
    event.pop("message", None)
    # The SDK copies incoming baggage from the trace context into envelope headers.
    event.get("contexts", {}).pop("trace", None)
    if "exception" in event:
        for exception in event["exception"]["values"]:
            exception.pop("value", None)
    return event


def initialize_sentry(dsn: str, environment: str, release: str) -> None:
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        max_breadcrumbs=0,
        traces_sample_rate=None,
        profile_session_sample_rate=0.0,
        auto_session_tracking=False,
        disabled_integrations=[LoggingIntegration],
        before_send=_strip_sensitive_data,
    )
