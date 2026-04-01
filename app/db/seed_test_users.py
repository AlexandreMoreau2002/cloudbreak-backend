"""
Seed — Users de test pour development.

Crée des comptes de test avec différents plans (freemium, pro, premium).
Chaque compte a un user_id Supabase fictif pour le développement local.

Usage:
    make seed-test      # Insérer les users
    make unseed-test    # Supprimer les users
    make reset-db       # Reset complète (drop + recreate)

Comptes créés:
    - user-freemium-001 / freemium@cloudbreak.fr (gratuit, 1 check/jour)
    - user-pro-001 / pro@cloudbreak.fr (illimité, valide 1 an)
    - user-admin-001 / admin@cloudbreak.fr (admin, illimité)
"""

import asyncio
import logging
from app.core.config import settings
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from app.models.subscription import Subscription
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

logger = logging.getLogger(__name__)


# Comptes de test prédéfinis
TEST_USERS = {
    "freemium": {
        "user_id": "user-freemium-001",
        "email": "freemium@cloudbreak.fr",
        "plan": "free",
        "expires_at": None,  # Pas d'expiration (free)
    },
    "pro": {
        "user_id": "user-pro-001",
        "email": "pro@cloudbreak.fr",
        "plan": "pro",
        "expires_at": datetime.utcnow() + timedelta(days=365),
    },
    "admin": {
        "user_id": "user-admin-001",
        "email": "admin@cloudbreak.fr",
        "plan": "pro",
        "expires_at": datetime.utcnow() + timedelta(days=365),
    },
}


async def seed_test_users() -> None:
    """Insère les comptes de test."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Créer la table si elle n'existe pas (dev)
        async with engine.begin() as conn:
            await conn.run_sync(Subscription.metadata.create_all)

        # Insérer les users
        for user_type, user_data in TEST_USERS.items():
            subscription = Subscription(
                user_id=user_data["user_id"],
                plan=user_data["plan"],
                expires_at=user_data["expires_at"],
            )
            session.add(subscription)

            logger.info(
                "seed_test_user",
                extra={
                    "user_id": user_data["user_id"],
                    "email": user_data["email"],
                    "plan": user_data["plan"],
                },
            )

        await session.commit()
        logger.info("seed_test_users_completed", extra={"count": len(TEST_USERS)})

    await engine.dispose()


async def unseed_test_users() -> None:
    """Supprime les comptes de test."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for user_type, user_data in TEST_USERS.items():
            from sqlalchemy import delete

            stmt = delete(Subscription).where(Subscription.user_id == user_data["user_id"])
            await session.execute(stmt)
            logger.info("unseed_test_user", extra={"user_id": user_data["user_id"]})

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
