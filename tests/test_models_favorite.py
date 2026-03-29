from app.models.favorite import Favorite


def test_favorite_model_table_and_constraints() -> None:
    assert Favorite.__tablename__ == "user_favorites"
    constraints = {constraint.name for constraint in Favorite.__table__.constraints}

    assert "uq_user_peak" in constraints
    assert Favorite.__table__.columns["peak_id"].nullable is False
