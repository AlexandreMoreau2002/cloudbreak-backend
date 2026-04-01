import json
from typing import Any

from jose import JWTError, jwt
from jose.backends import ECKey

from app.core.errors import ErrorCode


def decode_supabase_jwt(token: str, jwks_json: str) -> dict[str, object]:
    """Valide un JWT Supabase localement via la clé publique ECC (P-256).
    Zéro appel réseau — la clé publique est chargée depuis les variables d'environnement.
    """
    try:
        jwk = json.loads(jwks_json)
        public_key = ECKey(jwk, algorithm="ES256")
        payload: dict[str, object] = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
        return payload
    except JWTError as e:
        raise ValueError(f"{ErrorCode.INVALID_TOKEN}: {e}") from e


def encode_test_jwt(payload: dict[str, Any]) -> str:
    """
    Génère un JWT de test (signature FAKE).

    ⚠️ DEV/TEST ONLY — Ne jamais utiliser en production.

    Usage:
        token = encode_test_jwt({
            "sub": "user-123",
            "email": "test@example.com",
            "exp": timestamp,
        })

    Returns:
        JWT string avec signature fake
    """
    secret_key = "dev-secret-key-very-insecure-do-not-use-in-prod"
    token: str = jwt.encode(payload, secret_key, algorithm="HS256")
    return token
