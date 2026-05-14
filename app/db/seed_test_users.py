"""
Seed — Users de test pour development.

Crée des comptes de test avec différents plans (freemium, pro, premium).
Chaque compte correspond à un user Supabase réel (UUIDs Supabase cloud).

Usage:
    make seed-test      # Insérer les users
    make unseed-test    # Supprimer les users
    make reset-db       # Reset complète (drop + recreate)

Comptes créés (UUIDs Supabase réels):
    - ddce4acf-4588-4916-bb8e-8e47de082e7b / freemium@cloudbreak.app (gratuit, 1 check/jour)
    - d19f15c6-ab8c-4eee-89a2-cc3c2342a3a5 / pro@cloudbreak.app (illimité, valide 1 an)
    - 6f12c6e6-5478-4301-8494-83ab039c53aa / test@cloudbreak.app (illimité, valide 1 an)
"""

import asyncio
import logging
from app.core.config import settings
from datetime import UTC, datetime, timedelta
from app.models.subscription import Subscription
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


# Comptes de test prédéfinis — UUIDs Supabase réels
TEST_USERS: dict[str, dict[str, str | datetime | None]] = {
    "freemium": {
        "user_id": "ddce4acf-4588-4916-bb8e-8e47de082e7b",
        "email": "freemium@cloudbreak.app",
        "plan": "free",
        "expires_at": None,  # Pas d'expiration (free)
    },
    "pro": {
        "user_id": "d19f15c6-ab8c-4eee-89a2-cc3c2342a3a5",
        "email": "pro@cloudbreak.app",
        "plan": "pro",
        "expires_at": datetime.now(UTC) + timedelta(days=365),
    },
    "test": {
        "user_id": "6f12c6e6-5478-4301-8494-83ab039c53aa",
        "email": "test@cloudbreak.app",
        "plan": "pro",
        "expires_at": datetime.now(UTC) + timedelta(days=365),
    },
}


async def seed_test_users() -> None:
    """Insère les comptes de test."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Créer la table si elle n'existe pas (dev)
        async with engine.begin() as conn:
            await conn.run_sync(Subscription.metadata.create_all)

        # Insérer les users
        for user_type, user_data in TEST_USERS.items():
            subscription = Subscription(
                user_id=str(user_data["user_id"]),
                plan=str(user_data["plan"]),
                expires_at=user_data["expires_at"],
            )
            session.add(subscription)

            logger.info(
                "seed_test_user",
                extra={
                    "user_id": str(user_data["user_id"]),
                    "email": str(user_data["email"]),
                    "plan": str(user_data["plan"]),
                },
            )

        await session.commit()
        logger.info("seed_test_users_completed", extra={"count": len(TEST_USERS)})

    await engine.dispose()


async def unseed_test_users() -> None:
    """Supprime les comptes de test."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for user_type, user_data in TEST_USERS.items():
            from sqlalchemy import delete

            stmt = delete(Subscription).where(Subscription.user_id == str(user_data["user_id"]))
            await session.execute(stmt)
            logger.info("unseed_test_user", extra={"user_id": str(user_data["user_id"])})

        await session.commit()
        logger.info("unseed_test_users_completed", extra={"count": len(TEST_USERS)})

    await engine.dispose()


def main() -> None:
    """Point d'entrée CLI."""
    import sys

    action = sys.argv[1] if len(sys.argv) > 1 else "seed"

    logging.basicConfig(level=logging.INFO)

    if action == "seed":
        asyncio.run(seed_test_users())
    elif action == "unseed":
        asyncio.run(unseed_test_users())
    else:
        print(f"Unknown action: {action}")
        print("Usage: python -m app.db.seed_test_users [seed|unseed]")
        sys.exit(1)


if __name__ == "__main__":
    main()
