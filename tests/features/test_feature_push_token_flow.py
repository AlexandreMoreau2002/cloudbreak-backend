"""Feature test — flux HTTP complet du token push (enregistrement, transfert, retrait, RGPD).

Pas de Postgres dans la suite de tests : les « profils » vivent dans un dictionnaire en
mémoire, `get_or_create_user` et l'UPDATE de purge sont émulés au niveau de la session.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Update

from app.core.dependencies import get_current_user, get_redis
from app.db.session import get_db
from app.main import app
from app.schemas.user import UserProfile
from app.services.user import clear_push_token, set_push_token

TOKEN = "ExponentPushToken[device-1]"
USER_A = {"id": "user-a", "email": "a@test.com", "is_anonymous": False}
USER_B = {"id": "user-b", "email": "b@test.com", "is_anonymous": False}


class _FakeSession:
    """Session minimale : l'UPDATE de purge retire le token des autres profils."""

    def __init__(self, store: dict[str, SimpleNamespace]) -> None:
        self._store = store
        self.commit = AsyncMock()
        self.flush = AsyncMock()

    def begin_nested(self) -> AsyncMock:
        savepoint = AsyncMock()
        savepoint.__aenter__.return_value = None
        savepoint.__aexit__.return_value = False
        return savepoint

    async def execute(self, statement: object) -> None:
        if isinstance(statement, Update):
            # Hypothèse : SQLAlchemy nomme les paramètres liés `<colonne>_<n>` dans l'ordre
            # d'apparition (`push_token_1` pour le WHERE, `supabase_user_id_1`). Le SET
            # `push_token=None` est le paramètre `push_token` (sans suffixe), donc sans collision.
            # Si une montée de version SQLAlchemy change ce nommage, ce test casse ici.
            params = statement.compile().params
            owner = next(v for k, v in params.items() if k.startswith("supabase_user_id_"))
            token = next((v for k, v in params.items() if k.startswith("push_token_")), None)
            for profile in self._store.values():
                if token is None:  # clear_push_token : met à NULL le token de l'appelant
                    if profile.supabase_user_id == owner:
                        profile.push_token = None
                elif profile.push_token == token and profile.supabase_user_id != owner:
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

    redis = AsyncMock()
    redis.eval.return_value = 1

    async def override_redis() -> AsyncMock:
        return redis

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = override_redis
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


def test_delete_without_profile_does_not_create_one(store: dict[str, SimpleNamespace]) -> None:
    _as(USER_A)
    with TestClient(app) as client:
        response = client.delete("/api/v1/user/push-token")

    assert response.status_code == 204
    assert store == {}


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


@pytest.mark.asyncio
async def test_real_statements_compile_to_expected_postgres_sql() -> None:
    """Fige le SQL réel de la purge et du clear (le faux ci-dessus ne lit que des noms)."""
    captured: list[object] = []

    class _Recorder(_FakeSession):
        async def execute(self, statement: object) -> None:
            captured.append(statement)

    profile = SimpleNamespace(supabase_user_id="u1", push_token=None, push_token_valid=False)
    db = _Recorder({})

    with patch("app.services.user.get_or_create_user", AsyncMock(return_value=profile)):
        await set_push_token({"id": "u1"}, TOKEN, db)  # type: ignore[arg-type]
        await clear_push_token({"id": "u1"}, db)  # type: ignore[arg-type]

    purge, clear = (s.compile(dialect=postgresql.dialect()) for s in captured)  # type: ignore[attr-defined]
    assert str(purge) == (
        "UPDATE users SET push_token=%(push_token)s WHERE users.push_token = %(push_token_1)s "
        "AND users.supabase_user_id != %(supabase_user_id_1)s"
    )
    assert purge.params == {
        "push_token": None,
        "push_token_1": TOKEN,
        "supabase_user_id_1": "u1",
    }
    assert str(clear) == (
        "UPDATE users SET push_token=%(push_token)s WHERE users.supabase_user_id = "
        "%(supabase_user_id_1)s"
    )
