from app.models.peak import Peak


def test_peak_model_table_and_columns() -> None:
    assert Peak.__tablename__ == "peaks"
    columns = Peak.__table__.columns

    assert columns["id"].primary_key is True
    assert columns["slug"].unique is True
    assert columns["region"].nullable is True
