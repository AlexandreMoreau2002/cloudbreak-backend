"""
analytics — interface d'événements business.

Les événements autorisés sont envoyés à PostHog sans modifier les appelants.
Sans configuration, cette interface reste un no-op sans trafic réseau.
"""

import logging

from posthog import Posthog

logger = logging.getLogger(__name__)

AnalyticsProperties = dict[str, object]

_client: Posthog | None = None

_ALLOWED_PROPERTIES: dict[str, dict[str, type[object]]] = {
    "account_deleted": {},
    "favorite_added": {"peak_id": str},
    "favorite_alert_sent": {"peak_id": str, "score": int},
    "favorite_removed": {"peak_id": str},
    "quota_bypassed": {"plan": str},
    "quota_exceeded": {"peak_id": str, "plan": str},
    "score_calculated": {"peak_id": str, "plan": str, "score": int, "verdict": str},
    "score_week_calculated": {"cell_count": int, "peak_id": str, "plan": str},
    "terrain_validated": {"prediction_id": str, "result": bool},
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
    safe = {
        name: value
        for name, value in properties.items()
        if name in allowed and type(value) is allowed[name]
    }
    if properties and allowed and not safe:
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
