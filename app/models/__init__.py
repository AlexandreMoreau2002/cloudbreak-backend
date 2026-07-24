"""Import des modèles SQLAlchemy — requis pour Alembic autogenerate."""

from app.models.peak import Peak
from app.models.favorite import Favorite
from app.models.subscription import Subscription
from app.models.prediction import Prediction
from app.models.terrain_validation import TerrainValidation

__all__ = ["Favorite", "Peak", "Prediction", "Subscription", "TerrainValidation"]
