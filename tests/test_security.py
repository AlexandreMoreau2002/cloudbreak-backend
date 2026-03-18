import json
import time
import pytest
from jose import jwt
from jose.backends import ECKey
from app.core.security import decode_supabase_jwt

# Paire de clés ECC P-256 éphémère — tests uniquement
TEST_PRIVATE_JWK = {
    "x": "HGpCklI-j-RfFtZ2jYiGQuNvFzI27vthKfHjn8YRc8A",
    "y": "YQByzZt-ZOdAiAuzJIypZSY1slIjBZvViba1It2b9B8",
    "d": "_cK_OmehRWDsNLRPavguz6Dj9GV7Yf1IOWzD3C8QG-Y",
    "kty": "EC",
    "crv": "P-256",
    "alg": "ES256",
    "kid": "test-key",
}

TEST_PUBLIC_JWK = {k: v for k, v in TEST_PRIVATE_JWK.items() if k != "d"}


def _make_token(payload: dict) -> str:
    private_key = ECKey(TEST_PRIVATE_JWK, algorithm="ES256")
    return jwt.encode(payload, private_key, algorithm="ES256")


def test_decode_valid_token() -> None:
    payload = {
        "sub": "user-123",
        "email": "test@cloudbreak.app",
        "exp": int(time.time()) + 3600,
    }
    token = _make_token(payload)
    result = decode_supabase_jwt(token, json.dumps(TEST_PUBLIC_JWK))
    assert result["sub"] == "user-123"
    assert result["email"] == "test@cloudbreak.app"


def test_decode_invalid_token() -> None:
    with pytest.raises(ValueError):
        decode_supabase_jwt("not.a.valid.token", json.dumps(TEST_PUBLIC_JWK))


def test_decode_expired_token() -> None:
    payload = {
        "sub": "user-123",
        "exp": int(time.time()) - 3600,
    }
    token = _make_token(payload)
    with pytest.raises(ValueError):
        decode_supabase_jwt(token, json.dumps(TEST_PUBLIC_JWK))
