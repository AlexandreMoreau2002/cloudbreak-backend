"""
analytics — interface d'événements business.

Stub : log DEBUG uniquement, aucun appel réseau. PostHog sera branché
derrière cette interface dans la story 1.5, sans toucher les appelants.

Usage :
  from app.services.analytics import track
  track("score_calculated", user_id, {"peak_id": peak_id, "verdict": verdict})
"""

import logging

logger = logging.getLogger(__name__)


def track(event: str, user_id: str, properties: dict[str, object] | None = None) -> None:
    logger.debug(
        "analytics_event",
        extra={"event": event, "user_id": user_id, "properties": properties or {}},
    )
