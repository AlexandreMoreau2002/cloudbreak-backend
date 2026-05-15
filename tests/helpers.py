"""
Helpers partagés pour les tests — DEV/TEST ONLY.

Ne jamais importer ces fonctions dans le code de production.
"""

from jose import jwt
from typing import Any


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
