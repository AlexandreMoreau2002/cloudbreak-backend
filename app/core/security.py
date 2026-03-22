import json

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
