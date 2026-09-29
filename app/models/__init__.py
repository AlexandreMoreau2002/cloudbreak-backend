"""Import des modèles SQLAlchemy — requis pour Alembic autogenerate."""

from app.models.peak import Peak
from app.models.favorite import Favorite
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.apple_subscription_event import AppleSubscriptionEvent
from app.models.terrain_validation import TerrainValidation
from app.models.user import User

__all__ = [
    "AppleSubscriptionEvent",
    "Favorite",
    "Peak",
    "Prediction",
    "Subscription",
    "TerrainValidation",
    "User",
]
