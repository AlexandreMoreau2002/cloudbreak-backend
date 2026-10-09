"""Feature test — flux HTTP complet du token push (enregistrement, transfert, retrait, RGPD).

Pas de Postgres dans la suite de tests : les « profils » vivent dans un dictionnaire en
mémoire, `get_or_create_user` et l'UPDATE de purge sont émulés au niveau de la session.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql.dml import Update

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.schemas.user import UserProfile

TOKEN = "ExponentPushToken[device-1]"
USER_A = {"id": "user-a", "email": "a@test.com", "is_anonymous": False}
USER_B = {"id": "user-b", "email": "b@test.com", "is_anonymous": False}


class _FakeSession:
    """Session minimale : l'UPDATE de purge retire le token des autres profils."""

    def __init__(self, store: dict[str, SimpleNamespace]) -> None:
        self._store = store
        self.commit = AsyncMock()
        self.flush = AsyncMock()

    async def execute(self, statement: object) -> None:
        if isinstance(statement, Update):
            # Hypothèse : SQLAlchemy nomme les paramètres liés `<colonne>_<n>` dans l'ordre
            # d'apparition (`push_token_1` pour le WHERE, `supabase_user_id_1`). Le SET
            # `push_token=None` est un littéral NULL, pas un paramètre, donc sans collision.
            # Si une montée de version SQLAlchemy change ce nommage, ce test casse ici.
            params = statement.compile().params
            token = next(v for k, v in params.items() if k.startswith("push_token_"))
            owner = next(v for k, v in params.items() if k.startswith("supabase_user_id_"))
            for profile in self._store.values():
                if profile.push_token == token and profile.supabase_user_id != owner:
                    profile.push_token = None


@pytest.fixture
def store() -> Iterator[dict[str, SimpleNamespace]]:
    profiles: dict[str, SimpleNamespace] = {}

    async def fake_get_or_create(
        user_id: str, auth_provider: str, db: object, email: str | None = None
    ) -> SimpleNamespace:
        return profiles.setdefault(
            user_id,
            SimpleNamespace(supabase_user_id=user_id, push_token=None, push_token_valid=False),
        )

    async def fake_delete_user_data(user_id: str, db: object) -> None:
        profiles.pop(user_id, None)

    async def override_db() -> object:
        yield _FakeSession(profiles)

    app.dependency_overrides[get_db] = override_db
    with (
        patch("app.services.user.get_or_create_user", fake_get_or_create),
        patch("app.api.v1.endpoints.user.delete_user_data", fake_delete_user_data),
        patch("app.api.v1.endpoints.user.delete_supabase_user", new_callable=AsyncMock),
    ):
        try:
            yield profiles
        finally:
            app.dependency_overrides.clear()


def _as(user: dict[str, object]) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def test_register_stores_token_and_marks_valid(store: dict[str, SimpleNamespace]) -> None:
    _as(USER_A)
    with TestClient(app) as client:
        response = client.post("/api/v1/user/push-token", json={"push_token": TOKEN})

    assert response.status_code == 204
    assert store["user-a"].push_token == TOKEN
    assert store["user-a"].push_token_valid is True


def test_same_token_on_second_account_is_removed_from_first(
    store: dict[str, SimpleNamespace],
) -> None:
    with TestClient(app) as client:
        _as(USER_A)
        client.post("/api/v1/user/push-token", json={"push_token": TOKEN})
        _as(USER_B)
        client.post("/api/v1/user/push-token", json={"push_token": TOKEN})

    assert store["user-a"].push_token is None
    assert store["user-b"].push_token == TOKEN


def test_delete_clears_token(store: dict[str, SimpleNamespace]) -> None:
    _as(USER_A)
    with TestClient(app) as client:
        client.post("/api/v1/user/push-token", json={"push_token": TOKEN})
        response = client.delete("/api/v1/user/push-token")

    assert response.status_code == 204
    assert store["user-a"].push_token is None


def test_account_deletion_removes_profile_and_token(store: dict[str, SimpleNamespace]) -> None:
    _as(USER_A)
    with TestClient(app) as client:
        client.post("/api/v1/user/push-token", json={"push_token": TOKEN})
        response = client.delete("/api/v1/user")

    assert response.status_code == 204
    assert "user-a" not in store


def test_push_token_is_never_exposed_by_user_profile() -> None:
    assert "push_token" not in UserProfile.model_fields
    assert "push_token_valid" not in UserProfile.model_fields
