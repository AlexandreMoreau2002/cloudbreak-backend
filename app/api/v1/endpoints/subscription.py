"""Authenticated StoreKit 2 entitlement read and verification routes."""

from uuid import UUID
from typing import cast
from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.config import settings
from app.schemas.subscription import (
    SubscriptionResponse,
    SubscriptionStatus,
    SubscriptionVerifyRequest,
)
from app.services.apple_store import (
    AppleSignedDataVerifier,
    AppleStoreBundleError,
    AppleStoreEnvironmentError,
    AppleStoreProductError,
    AppleStoreTransactionError,
)
from app.services.subscription import (
    SubscriptionOwnershipConflict,
    apply_verified_transaction,
    get_subscription_response,
)
from app.core.errors import ApiError, ErrorCode
from app.core.dependencies import get_current_user, get_permanent_user

router = APIRouter(prefix="/api/v1/user/subscription", tags=["subscription"])


def get_apple_signed_data_verifier() -> AppleSignedDataVerifier:
    """Build the verifier from deployment configuration, not request data."""
    return AppleSignedDataVerifier(
        bundle_id=settings.apple_bundle_id,
        environment=settings.apple_environment,
        app_apple_id=settings.apple_app_id,
        allowed_product_ids=(
            "com.alexandremoreau.cloudbreak.premium.monthly",
            "com.alexandremoreau.cloudbreak.premium.annual",
        ),
    )


@router.get("", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: dict[str, object] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    """Return the current entitlement for any authenticated user."""
    return await get_subscription_response(str(current_user["id"]), db)


@router.post("/verify", response_model=SubscriptionResponse)
async def verify_subscription(
    payload: SubscriptionVerifyRequest,
    current_user: dict[str, object] = Depends(get_permanent_user),
    db: AsyncSession = Depends(get_db),
    verifier: AppleSignedDataVerifier = Depends(get_apple_signed_data_verifier),
) -> SubscriptionResponse:
    """Verify a StoreKit-signed transaction then atomically persist its entitlement."""
    try:
        transaction = verifier.verify_transaction(payload.signed_transaction)
    except (AppleStoreProductError, AppleStoreBundleError, AppleStoreEnvironmentError):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "Transaction Apple non prise en charge",
            ErrorCode.APPLE_TRANSACTION_UNSUPPORTED,
        ) from None
    except AppleStoreTransactionError:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "Transaction Apple invalide",
            ErrorCode.APPLE_TRANSACTION_INVALID,
        ) from None

    try:
        user_id = UUID(str(current_user["id"]))
    except ValueError:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "Compte invalide pour une transaction Apple",
            ErrorCode.APPLE_TRANSACTION_INVALID,
        ) from None
    if transaction.app_account_token != user_id:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "Transaction Apple non liée à ce compte",
            ErrorCode.APPLE_TRANSACTION_INVALID,
        )

    try:
        subscription = await apply_verified_transaction(str(user_id), transaction, db)
        await db.commit()
    except SubscriptionOwnershipConflict:
        await db.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "Cet abonnement est déjà associé à un autre compte",
            ErrorCode.SUBSCRIPTION_OWNERSHIP_CONFLICT,
        ) from None

    return SubscriptionResponse(
        plan="premium" if subscription.plan in {"premium", "pro"} else "free",
        status=cast(SubscriptionStatus, subscription.status),
        expires_at=cast(datetime | None, subscription.expires_at),
    )
