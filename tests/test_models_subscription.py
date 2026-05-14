from app.models.subscription import Subscription


def test_subscription_repr() -> None:
    subscription = Subscription(user_id="user-123", plan="pro")

    assert repr(subscription) == "<Subscription user_id=user-123 plan=pro>"
