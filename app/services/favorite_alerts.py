"""Alertes push favoris (story 5.2) : sélection des candidats, score, déduplication, envoi.

Appelé par `POST /internal/notifications/run-favorites` (cron). Aucune alerte régionale.
"""

import logging
from typing import Any, cast
from dataclasses import dataclass
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.peak import Peak
from app.models.user import User
from app.services.weather import WeatherService
from app.models.favorite import Favorite
from app.domain.score import calculate_score
from app.services.analytics import track
from app.models.subscription import Subscription
from app.domain.entitlement import ACTIVE_STATUSES, PREMIUM_PLANS, is_entitlement_active
from app.services.notifications import send_push_to_user
from app.domain.favorite_alerts import (
    ALERT_HOUR,
    DEDUPE_TTL_SECONDS,
    alert_dedupe_key,
    is_alert_worthy,
    target_alert_date,
    build_favorite_alert,
)

logger = logging.getLogger(__name__)

MAX_ROWS = 2000
MAX_ALERTS_PER_RUN = 500

SendFn = Callable[..., Awaitable[bool]]


@dataclass
class Candidate:
    user: User
    peak: Peak


async def fetch_candidates(db: AsyncSession, now: datetime | None = None) -> list[Candidate]:
    """Couples (utilisateur Premium actif, sommet favori) à évaluer.

    Le filtre Premium est appliqué en SQL (avant la limite) pour que des non-Premium ne
    puissent pas évincer des abonnés ; `is_entitlement_active` reste le filet de sécurité
    (même source de vérité des plans et statuts).
    """
    moment = now or datetime.now(UTC)
    statement = (
        select(User, Peak, Subscription)
        .join(Favorite, Favorite.user_id == User.supabase_user_id)
        .join(Peak, Peak.id == Favorite.peak_id)
        .join(Subscription, Subscription.user_id == User.supabase_user_id)
        .where(
            Subscription.plan.in_(sorted(PREMIUM_PLANS)),
            Subscription.status.in_(sorted(ACTIVE_STATUSES)),
            Subscription.expires_at > moment,
            User.notif_favorites.is_(True),
            User.push_token.is_not(None),
            User.push_token_valid.is_(True),
        )
        .order_by(User.supabase_user_id, Peak.id)
        .limit(MAX_ROWS)
    )
    rows = (await db.execute(statement)).all()
    if len(rows) >= MAX_ROWS:
        logger.warning("favorite_alerts_truncated", extra={"limit": MAX_ROWS})
    return [
        Candidate(user=user, peak=peak)
        for user, peak, subscription in rows
        if subscription is not None
        and is_entitlement_active(
            cast(str | None, subscription.plan),
            cast(str | None, subscription.status),
            cast(datetime | None, subscription.expires_at),
            moment,
        )
    ]


@dataclass
class AlertSummary:
    candidates: int = 0
    peaks_scored: int = 0
    alerts_sent: int = 0
    skipped_not_ideal: int = 0
    skipped_already_sent: int = 0
    skipped_cap: int = 0
    send_failed: int = 0
    weather_failed: int = 0


async def _score_peak(
    weather_service: WeatherService, peak: Peak, date: str
) -> dict[str, Any] | None:
    """Score du sommet pour `date` 6h, ou None si la météo est indisponible. Ne lève jamais."""
    try:
        weather = await weather_service.get_forecast(
            lat=float(cast(float, peak.lat)),
            lng=float(cast(float, peak.lng)),
            date=date,
            hour=ALERT_HOUR,
        )
        return cast(
            dict[str, Any],
            calculate_score(weather, peak_altitude=int(cast(int, peak.altitude))),
        )
    except Exception as error:
        logger.error(
            "favorite_alert_weather_failed",
            extra={"peak_id": str(peak.id), "date": date, "error": type(error).__name__},
        )
        return None


async def process_candidates(
    candidates: list[Candidate],
    *,
    redis: Redis,
    weather_service: WeatherService,
    date: str,
    send: SendFn = send_push_to_user,
) -> AlertSummary:
    summary = AlertSummary(candidates=len(candidates))
    scores: dict[str, dict[str, Any] | None] = {}

    for candidate in candidates:
        peak_id = str(candidate.peak.id)
        if peak_id not in scores:
            scores[peak_id] = await _score_peak(weather_service, candidate.peak, date)
            if scores[peak_id] is None:
                summary.weather_failed += 1
            else:
                summary.peaks_scored += 1
        result = scores[peak_id]
        if result is None:
            continue
        if not is_alert_worthy(str(result["verdict"])):
            summary.skipped_not_ideal += 1
            continue
        if summary.alerts_sent >= MAX_ALERTS_PER_RUN:
            summary.skipped_cap += 1
            continue

        user_id = str(candidate.user.supabase_user_id)
        key = alert_dedupe_key(user_id, peak_id, date)
        if not await redis.set(key, "1", nx=True, ex=DEDUPE_TTL_SECONDS):
            summary.skipped_already_sent += 1
            continue

        title, body = build_favorite_alert(
            str(candidate.peak.name), int(result["score"]), cast(str | None, candidate.user.locale)
        )
        data = {"type": "favorite_alert", "slug": str(candidate.peak.slug), "peak_id": peak_id}
        try:
            sent = await send(candidate.user, title, body, data)
        except Exception as error:
            logger.error(
                "favorite_alert_send_raised",
                extra={"user_id": user_id, "peak_id": peak_id, "error": type(error).__name__},
            )
            sent = False
        if sent:
            summary.alerts_sent += 1
            track(
                "favorite_alert_sent", user_id, {"peak_id": peak_id, "score": int(result["score"])}
            )
        else:
            await redis.delete(key)
            summary.send_failed += 1

    logger.info("favorite_alerts_run", extra=dict(summary.__dict__))
    return summary


async def run_favorite_alerts(
    db: AsyncSession,
    redis: Redis,
    weather_service: WeatherService,
    now: datetime | None = None,
) -> AlertSummary:
    moment = now or datetime.now(UTC)
    candidates = await fetch_candidates(db, moment)
    return await process_candidates(
        candidates,
        redis=redis,
        weather_service=weather_service,
        date=target_alert_date(moment),
    )
