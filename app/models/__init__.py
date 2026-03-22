"""Import des modèles SQLAlchemy — requis pour Alembic autogenerate."""

from app.models.favorite import Favorite
from app.models.peak import Peak

__all__ = ["Favorite", "Peak"]
