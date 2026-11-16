"""
analytics — interface d'événements business.

Les événements autorisés sont envoyés à PostHog sans modifier les appelants.
Sans configuration, cette interface reste un no-op sans trafic réseau.
"""

import re
import logging
from collections.abc import Callable

from posthog import Posthog

logger = logging.getLogger(__name__)

AnalyticsProperties = dict[str, object]
PropertyValidator = Callable[[object], bool]

_client: Posthog | None = None

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID_PATTERN.fullmatch(value) is not None


def _is_enum(*allowed: str) -> PropertyValidator:
    return lambda value: isinstance(value, str) and value in allowed


def _is_integer_in_range(minimum: int, maximum: int) -> PropertyValidator:
    return lambda value: type(value) is int and minimum <= value <= maximum


def _is_boolean(value: object) -> bool:
    return type(value) is bool


_ALLOWED_PROPERTIES: dict[str, dict[str, PropertyValidator]] = {
    "account_deleted": {},
    "favorite_added": {"peak_id": _is_uuid},
    "favorite_alert_sent": {"peak_id": _is_uuid, "score": _is_integer_in_range(0, 100)},
    "favorite_removed": {"peak_id": _is_uuid},
    "quota_bypassed": {"plan": _is_enum("free", "premium", "pro")},
    "quota_exceeded": {"peak_id": _is_uuid, "plan": _is_enum("free", "premium", "pro")},
    "score_calculated": {
        "peak_id": _is_uuid,
        "plan": _is_enum("free", "premium", "pro"),
        "score": _is_integer_in_range(0, 100),
        "verdict": _is_enum("none", "high", "medium", "low"),
    },
    "score_week_calculated": {
        "cell_count": _is_integer_in_range(0, 63),
        "peak_id": _is_uuid,
        "plan": _is_enum("free", "premium", "pro"),
    },
    "terrain_validated": {"prediction_id": _is_uuid, "result": _is_boolean},
}


def initialize_analytics(api_key: str, host: str) -> None:
    """Initialise un client PostHog tamponné seulement si sa configuration est complète."""
    global _client

    if _client is not None or not api_key.strip() or not host.strip():
        return

    _client = Posthog(
        api_key,
        host=host,
        disable_geoip=True,
        capture_trace_context=False,
        enable_exception_autocapture=False,
        enable_local_evaluation=False,
        privacy_mode=True,
    )


def shutdown_analytics() -> None:
    """Vide le tampon PostHog lors de l'arrêt sans empêcher le shutdown de l'API."""
    global _client

    if _client is None:
        return

    _client.shutdown()
    _client = None


def _safe_properties(event: str, properties: AnalyticsProperties) -> AnalyticsProperties | None:
    allowed = _ALLOWED_PROPERTIES[event]
    safe: AnalyticsProperties = {}
    for name, value in properties.items():
        validator = allowed.get(name)
        if validator is None:
            continue
        if not validator(value):
            return None
        safe[name] = value

    if properties and not safe:
        return None
    return safe


def track(event: str, user_id: str, properties: AnalyticsProperties | None = None) -> None:
    """Ajoute un événement produit filtré à la file PostHog sans bloquer l'appelant."""
    if _client is None or event not in _ALLOWED_PROPERTIES:
        return

    safe_properties = _safe_properties(event, properties or {})
    if safe_properties is None:
        logger.warning("analytics_event_rejected", extra={"event": event})
        return

    _client.capture(distinct_id=user_id, event=event, properties=safe_properties)
