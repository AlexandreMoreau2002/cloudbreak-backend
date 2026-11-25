import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.subscription import Subscription
from app.models.user import User
from app.services import admin_users

KEY = "k" * 32
ADMIN = "admin-uuid"
EMAIL = "Alex.Secret@example.com"


@pytest.fixture(autouse=True)
def _hash_key():
    with patch("app.services.admin_users.settings.audit_hash_key", KEY):
        yield


def _db(user: User | None = None, sub: Subscription | None = None, found_id: str | None = None):
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = found_id
    db.execute.return_value = result

    async def get(model, key, **kwargs):
        return user if model is User else sub

    db.get.side_effect = get
    return db


def _audits(db):
    return [c.args[0] for c in db.add.call_args_list if hasattr(c.args[0], "action")]


def test_hash_is_stable_case_insensitive_and_hides_email() -> None:
    digest = admin_users.hash_email(EMAIL)
    assert digest == admin_users.hash_email("  alex.secret@EXAMPLE.com ")
    assert len(digest) == 64 and "secret" not in digest


def test_hash_refuses_without_key() -> None:
    with patch("app.services.admin_users.settings.audit_hash_key", ""):
        with pytest.raises(admin_users.AuditDisabled):
            admin_users.hash_email(EMAIL)


async def test_lookup_found_audits_hash_and_user_id_without_email(caplog) -> None:
    sub = Subscription(user_id="u1", plan="premium", status="active", origin="granted")
    sub.expires_at = datetime.now(UTC) + timedelta(days=3)
    db = _db(found_id="u1", sub=sub)
    with caplog.at_level(logging.DEBUG):
        view = await admin_users.lookup_user(db, ADMIN, EMAIL)
    assert view.user_id == "u1" and view.premium_active and view.origin == "granted"
    (audit,) = _audits(db)
    assert audit.action == "user.lookup" and audit.result == "success"
    assert audit.actor_id == ADMIN and audit.target_user_id == "u1"
    assert audit.target_hash == admin_users.hash_email(EMAIL)
    dumped = " ".join(str(getattr(audit, c.name)) for c in audit.__table__.columns)
    assert "secret" not in dumped.lower() and "secret" not in caplog.text.lower()
    db.commit.assert_awaited_once()


async def test_lookup_without_subscription_is_free() -> None:
    view = await admin_users.lookup_user(_db(found_id="u1"), ADMIN, EMAIL)
    assert (view.plan, view.status, view.origin, view.premium_active) == (
        "free",
        "none",
        None,
        False,
    )


async def test_lookup_not_found_is_audited() -> None:
    db = _db()
    with pytest.raises(admin_users.UserNotFound):
        await admin_users.lookup_user(db, ADMIN, EMAIL)
    (audit,) = _audits(db)
    assert audit.result == "not_found" and audit.target_user_id is None
    assert audit.target_hash == admin_users.hash_email(EMAIL)
    db.commit.assert_awaited_once()


async def test_grant_creates_granted_subscription() -> None:
    db = _db(user=User(supabase_user_id="u1"))
    before = datetime.now(UTC)
    view = await admin_users.grant_premium(db, ADMIN, "u1", 30)
    assert view.premium_active and view.origin == "granted" and view.status == "active"
    assert view.expires_at is not None
    assert before + timedelta(days=30) <= view.expires_at <= datetime.now(UTC) + timedelta(days=30)
    audit = _audits(db)[0]
    assert (audit.action, audit.result, audit.grant_days) == ("subscription.grant", "success", 30)
    assert audit.target_user_id == "u1" and audit.target_hash is None


async def test_grant_extends_active_granted_subscription() -> None:
    end = datetime.now(UTC) + timedelta(days=10)
    sub = Subscription(user_id="u1", plan="premium", status="active", origin="granted")
    sub.expires_at = end
    view = await admin_users.grant_premium(
        _db(user=User(supabase_user_id="u1"), sub=sub), ADMIN, "u1", 5
    )
    assert view.expires_at == end + timedelta(days=5)


async def test_grant_restarts_from_now_when_expired_keeps_apple_ids() -> None:
    sub = Subscription(user_id="u1", plan="premium", status="expired", origin="apple")
    sub.expires_at = datetime.now(UTC) - timedelta(days=2)
    sub.original_transaction_id = "orig"
    view = await admin_users.grant_premium(
        _db(user=User(supabase_user_id="u1"), sub=sub), ADMIN, "u1", 7
    )
    assert view.premium_active and view.origin == "granted"
    assert sub.original_transaction_id == "orig"


@pytest.mark.parametrize("status", ["active", "trial"])
async def test_grant_refuses_active_apple_subscription(status: str) -> None:
    sub = Subscription(user_id="u1", plan="premium", status=status, origin="apple")
    sub.expires_at = datetime.now(UTC) + timedelta(days=20)
    db = _db(user=User(supabase_user_id="u1"), sub=sub)
    with pytest.raises(admin_users.AppleSubscriptionActive):
        await admin_users.grant_premium(db, ADMIN, "u1", 30)
    assert sub.origin == "apple" and sub.status == status
    assert _audits(db)[0].result == "conflict"
    db.commit.assert_awaited_once()


async def test_grant_unknown_user_is_audited() -> None:
    db = _db()
    with pytest.raises(admin_users.UserNotFound):
        await admin_users.grant_premium(db, ADMIN, "ghost", 30)
    assert _audits(db)[0].result == "not_found"
