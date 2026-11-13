"""Règles pures des alertes push favoris (story 5.2) — sans I/O.

Une alerte est envoyée pour un sommet favori dont le verdict du lendemain 6h est `high`
(toutes les conditions du verdict `high` : voir `app/domain/score*.py`, non modifié ici).
"""

from datetime import datetime, timedelta

from app.domain.score_context import PARIS_TZ

ALERT_HOUR = 6
DEDUPE_TTL_SECONDS = 36 * 3600
MAX_PEAK_NAME_LENGTH = 80

SUPPORTED_LOCALES = ("fr", "en")
DEFAULT_LOCALE = "fr"

_MESSAGES = {
    "fr": (
        "Mer de nuage demain",
        "Conditions idéales prévues demain {hour}h sur {peak} — {score}% 🟢",
    ),
    "en": (
        "Cloud sea tomorrow",
        "Ideal conditions forecast tomorrow at {hour} am at {peak} — {score}% 🟢",
    ),
}


def target_alert_date(now: datetime) -> str:
    """Date ISO du lendemain, jour calendaire Europe/Paris."""
    return (now.astimezone(PARIS_TZ) + timedelta(days=1)).date().isoformat()


def is_alert_worthy(verdict: str) -> bool:
    return verdict == "high"


def resolve_locale(locale: str | None) -> str:
    """Langue supportée, ou le français par défaut (compte sans langue enregistrée)."""
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def build_favorite_alert(peak_name: str, score: int, locale: str | None = None) -> tuple[str, str]:
    title, template = _MESSAGES[resolve_locale(locale)]
    if len(peak_name) > MAX_PEAK_NAME_LENGTH:
        peak_name = peak_name[:MAX_PEAK_NAME_LENGTH] + "…"  # payload Expo limité à 4 Ko
    return title, template.format(hour=ALERT_HOUR, peak=peak_name, score=score)


def alert_dedupe_key(user_id: str, peak_id: str, date: str) -> str:
    return f"notif:fav:{user_id}:{peak_id}:{date}"
