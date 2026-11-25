from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin
from app.db.session import get_db
from app.main import app
from app.schemas.admin import AdminUserSubscription
from app.services import admin_users

LOOKUP = "/api/v1/admin/users/lookup"
GRANT = "/api/v1/admin/users/grant-premium"
VIEW = AdminUserSubscription(
    user_id="u1",
    plan="premium",
    status="active",
    expires_at=datetime.now(UTC) + timedelta(days=30),
    origin="granted",
    premium_active=True,
)


@pytest.fixture
def admin():
    db = AsyncMock(spec=AsyncSession)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_admin] = lambda: {"id": "admin-1"}
    with patch("app.api.v1.endpoints.admin.settings.audit_hash_key", "k" * 32):
        yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "path,body", [(LOOKUP, {"email": "a@b.fr"}), (GRANT, {"user_id": "u", "days": 3})]
)
def test_non_admin_is_forbidden(path: str, body: dict) -> None:
    db = AsyncMock(spec=AsyncSession)
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post(path, json=body)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_FORBIDDEN"


@pytest.mark.parametrize("email", ["", "pas-un-email", "a@b", "partiel@", "@example.com"])
def test_lookup_invalid_email_is_422(admin: TestClient, email: str) -> None:
    assert admin.post(LOOKUP, json={"email": email}).status_code == 422


def test_lookup_missing_body_is_422(admin: TestClient) -> None:
    assert admin.post(LOOKUP, json={}).status_code == 422


def test_lookup_found(admin: TestClient) -> None:
    with patch.object(admin_users, "lookup_user", AsyncMock(return_value=VIEW)) as mock:
        response = admin.post(LOOKUP, json={"email": "a@b.fr"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "u1" and body["origin"] == "granted" and "email" not in body
    assert mock.await_args.args[1:] == ("admin-1", "a@b.fr")


def test_lookup_not_found_is_404(admin: TestClient) -> None:
    with patch.object(
        admin_users, "lookup_user", AsyncMock(side_effect=admin_users.UserNotFound())
    ):
        response = admin.post(LOOKUP, json={"email": "a@b.fr"})
    assert response.status_code == 404
    assert response.json()["code"] == "ADMIN_USER_NOT_FOUND"


def test_lookup_without_hash_key_is_503(admin: TestClient) -> None:
    with patch("app.services.admin_users.settings.audit_hash_key", ""):
        response = admin.post(LOOKUP, json={"email": "a@b.fr"})
    assert response.status_code == 503
    assert response.json()["code"] == "ADMIN_AUDIT_DISABLED"


@pytest.mark.parametrize("days", [0, -1, 367, "x"])
def test_grant_invalid_days_is_422(admin: TestClient, days: object) -> None:
    assert admin.post(GRANT, json={"user_id": "u1", "days": days}).status_code == 422


def test_grant_ok(admin: TestClient) -> None:
    with patch.object(admin_users, "grant_premium", AsyncMock(return_value=VIEW)) as mock:
        response = admin.post(GRANT, json={"user_id": "u1", "days": 30})
    assert response.status_code == 200 and response.json()["premium_active"] is True
    assert mock.await_args.args[1:] == ("admin-1", "u1", 30)


def test_grant_unknown_user_is_404(admin: TestClient) -> None:
    with patch.object(
        admin_users, "grant_premium", AsyncMock(side_effect=admin_users.UserNotFound())
    ):
        response = admin.post(GRANT, json={"user_id": "u1", "days": 30})
    assert response.status_code == 404


def test_grant_over_active_apple_is_409(admin: TestClient) -> None:
    with patch.object(
        admin_users, "grant_premium", AsyncMock(side_effect=admin_users.AppleSubscriptionActive())
    ):
        response = admin.post(GRANT, json={"user_id": "u1", "days": 30})
    assert response.status_code == 409
    assert response.json()["code"] == "ADMIN_APPLE_SUBSCRIPTION_ACTIVE"
