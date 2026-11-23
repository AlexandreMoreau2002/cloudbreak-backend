from app.models.admin_audit_log import AdminAuditLog


def test_audit_model_does_not_define_personal_fields() -> None:
    assert {"email", "secret"}.isdisjoint(AdminAuditLog.__table__.columns.keys())
