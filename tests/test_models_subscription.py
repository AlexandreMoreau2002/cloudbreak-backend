from app.models.subscription import Subscription


def test_subscription_repr() -> None:
    subscription = Subscription(user_id="user-123", plan="pro")

    assert repr(subscription) == "<Subscription user_id=user-123 plan=pro>"


def test_subscription_origin_defaults_to_apple() -> None:
    column = Subscription.__table__.columns["origin"]
    assert column.nullable is False
    assert column.default is not None
    assert column.default.arg == "apple"
