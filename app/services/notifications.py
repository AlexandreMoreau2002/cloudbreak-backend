"""Envoi de notifications push via l'API Expo Push (APNs derrière).

`send_push_to_user` ne lève jamais : une panne réseau ou un token mort ne doit pas
casser l'appelant (job d'alertes, endpoint). Le token n'est jamais loggué.
"""

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.core.config import settings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_TIMEOUT_SECONDS = 10.0


def _extract_ticket(body: object) -> dict[str, Any]:
    """Isole le ticket Expo (objet, ou premier élément d'une réponse batch)."""
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("Unexpected Expo response shape")
    return data


async def send_push_to_user(
    db: AsyncSession,
    user: User,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> bool:
    """Envoie un push à l'appareil de l'utilisateur. Retourne True si Expo a accepté.

    Sur `DeviceNotRegistered`, `push_token_valid` passe à false et la session est
    commitée ici, volontairement : l'invalidation doit survivre même si la transaction
    de l'appelant est annulée ensuite (sinon on réessaierait un token mort).
    """
    token = user.push_token
    if not token or not user.push_token_valid:
        return False

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if settings.expo_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_access_token}"
    payload = {"to": token, "title": title, "body": body, "data": data or {}, "sound": "default"}

    try:
        async with httpx.AsyncClient(timeout=EXPO_TIMEOUT_SECONDS) as client:
            response = await client.post(EXPO_PUSH_URL, json=payload, headers=headers)
            response.raise_for_status()
            ticket = _extract_ticket(response.json())
    except (httpx.HTTPError, ValueError) as error:
        logger.error(
            "push_send_failed",
            extra={"user_id": str(user.supabase_user_id), "error": type(error).__name__},
        )
        return False

    if ticket.get("status") == "ok":
        logger.info("push_sent", extra={"user_id": str(user.supabase_user_id)})
        return True

    error_code = (ticket.get("details") or {}).get("error")
    logger.error(
        "push_rejected",
        extra={"user_id": str(user.supabase_user_id), "expo_error": error_code},
    )
    if error_code == "DeviceNotRegistered":
        user.push_token_valid = False  # type: ignore[assignment]
        await db.commit()
    return False
