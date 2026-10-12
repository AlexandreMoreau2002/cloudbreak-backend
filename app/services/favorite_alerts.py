"""Alertes push favoris (story 5.2) : sélection des candidats, score, déduplication, envoi.

Appelé par `POST /internal/notifications/run-favorites` (cron). Aucune alerte régionale.
"""

import logging
from typing import cast
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.peak import Peak
from app.models.user import User
from app.models.favorite import Favorite
from app.models.subscription import Subscription
from app.domain.entitlement import is_entitlement_active

logger = logging.getLogger(__name__)

MAX_ROWS = 2000


@dataclass
class Candidate:
    user: User
    peak: Peak


async def fetch_candidates(db: AsyncSession, now: datetime | None = None) -> list[Candidate]:
    """Couples (utilisateur Premium actif, sommet favori) à évaluer."""
    moment = now or datetime.now(UTC)
    statement = (
        select(User, Peak, Subscription)
        .join(Favorite, Favorite.user_id == User.supabase_user_id)
        .join(Peak, Peak.id == Favorite.peak_id)
        .outerjoin(Subscription, Subscription.user_id == User.supabase_user_id)
        .where(
            User.notif_favorites.is_(True),
            User.push_token.is_not(None),
            User.push_token_valid.is_(True),
        )
        .order_by(User.supabase_user_id, Peak.id)
        .limit(MAX_ROWS)
    )
    rows = (await db.execute(statement)).all()
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
