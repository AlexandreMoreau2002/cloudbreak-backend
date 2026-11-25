"""Import des modèles SQLAlchemy — requis pour Alembic autogenerate."""

from app.models.user import User
from app.models.peak import Peak
from app.models.favorite import Favorite
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.terrain_validation import TerrainValidation
from app.models.apple_subscription_event import AppleSubscriptionEvent
from app.models.admin_audit_log import AdminAuditLog
from app.models.daily_stat import DailyStat
from app.models.cron_heartbeat import CronHeartbeat

__all__ = [
    "AppleSubscriptionEvent",
    "AdminAuditLog",
    "CronHeartbeat",
    "DailyStat",
    "Favorite",
    "Peak",
    "Prediction",
    "Subscription",
    "TerrainValidation",
    "User",
]
