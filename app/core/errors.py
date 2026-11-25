import json
import logging

logger = logging.getLogger(__name__)


def log_server_error(path: str, status: int, exc: BaseException) -> None:
    """Journalise une erreur 5xx en JSON : jamais de stack trace, ni message d'exception."""
    logger.error(
        json.dumps({"level": "error", "path": path, "status": status, "error": type(exc).__name__})
    )


class ApiError(Exception):
    """Erreur API dont le handler conserve le contrat de réponse direct."""

    def __init__(self, status_code: int, detail: str, code: str) -> None:
        self.status_code = status_code
        self.detail = detail
        self.code = code


class ErrorCode:
    NOT_FOUND = "NOT_FOUND"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    PEAK_NOT_FOUND = "PEAK_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    WEATHER_UNAVAILABLE = "WEATHER_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"
    ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
    INSTALLATION_ID_INVALID = "INSTALLATION_ID_INVALID"
    CLIENT_IP_UNAVAILABLE = "CLIENT_IP_UNAVAILABLE"
    APPLE_TRANSACTION_INVALID = "APPLE_TRANSACTION_INVALID"
    APPLE_TRANSACTION_UNSUPPORTED = "APPLE_TRANSACTION_UNSUPPORTED"
    SUBSCRIPTION_OWNERSHIP_CONFLICT = "SUBSCRIPTION_OWNERSHIP_CONFLICT"
    INTERNAL_AUTH_FAILED = "INTERNAL_AUTH_FAILED"
    INTERNAL_JOBS_DISABLED = "INTERNAL_JOBS_DISABLED"
    ADMIN_FORBIDDEN = "ADMIN_FORBIDDEN"
    HEARTBEAT_UNKNOWN_JOB = "HEARTBEAT_UNKNOWN_JOB"
    ADMIN_USER_NOT_FOUND = "ADMIN_USER_NOT_FOUND"
    ADMIN_APPLE_SUBSCRIPTION_ACTIVE = "ADMIN_APPLE_SUBSCRIPTION_ACTIVE"
    ADMIN_AUDIT_DISABLED = "ADMIN_AUDIT_DISABLED"
