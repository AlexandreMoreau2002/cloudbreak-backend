from app.models.admin_audit_log import AdminAuditLog


def test_audit_model_does_not_define_personal_fields() -> None:
    assert {"email", "secret"}.isdisjoint(AdminAuditLog.__table__.columns.keys())


def test_audit_model_has_target_columns_for_account_actions() -> None:
    assert {"target_hash", "target_user_id", "grant_days"} <= set(
        AdminAuditLog.__table__.columns.keys()
    )
