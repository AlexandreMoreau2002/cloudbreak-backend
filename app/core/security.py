import json
import httpx
from jose import JWTError, jwt
from jose.backends import ECKey
from fastapi import HTTPException
from app.core.errors import ErrorCode


def decode_supabase_jwt(token: str, jwks_json: str, supabase_url: str) -> dict[str, object]:
    """Valide un JWT Supabase localement via la clé publique ECC (P-256).
    Zéro appel réseau — la clé publique est chargée depuis les variables d'environnement.
    Vérifie aussi `aud` (doit être "authenticated", valeur standard Supabase Auth pour
    toute session y compris anonyme) et `iss` (doit correspondre au projet Supabase
    configuré) pour empêcher l'acceptation d'un token émis pour un autre contexte.
    """
    try:
        jwk = json.loads(jwks_json)
        public_key = ECKey(jwk, algorithm="ES256")
        payload: dict[str, object] = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            audience="authenticated",
            options={"require_aud": True},
        )
    except JWTError as e:
        raise ValueError(f"{ErrorCode.INVALID_TOKEN}: {e}") from e

    expected_issuer = f"{supabase_url}/auth/v1"
    if payload.get("iss") != expected_issuer:
        raise ValueError(f"{ErrorCode.INVALID_TOKEN}: issuer invalide")
    return payload


async def delete_supabase_user(user_id: str, supabase_url: str, service_role_key: str) -> None:
    """Supprime un utilisateur via l'API Admin Supabase.

    Args:
        user_id: UUID utilisateur Supabase
        supabase_url: URL du projet Supabase
        service_role_key: Clé service role (jamais exposée côté client)

    Raises:
        HTTPException(500) si la suppression échoue côté Supabase
    """
    url = f"{supabase_url}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.delete(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "Timeout suppression compte Supabase",
                    "code": ErrorCode.SERVICE_UNAVAILABLE,
                },
            ) from exc
    if response.status_code not in (200, 204):
        raise HTTPException(
            status_code=500,
            detail={"detail": "Erreur suppression compte", "code": ErrorCode.INTERNAL_ERROR},
        )
