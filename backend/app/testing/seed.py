"""Seed deterministic fixtures for the e2e stack.

Run inside the e2e backend container after migrations:
``python -m app.testing.seed``

Idempotent: an already-seeded database is left untouched.
"""

import asyncio
import os
import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select

from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.logs import configure_logging, get_logger
from app.users.models import User

logger = get_logger(__name__)

E2E_ADMIN_EMAIL = os.environ.get("BLINK_E2E_ADMIN_EMAIL", "e2e-admin@example.com")
E2E_ADMIN_PASSWORD = os.environ.get("BLINK_E2E_ADMIN_PASSWORD", "e2e-admin-password-123")


async def seed() -> bool:
    """Create the e2e admin account. Returns True if anything was created."""
    settings = get_settings()
    configure_logging(settings)
    engine = build_engine(settings.database_url)
    try:
        sessionmaker = build_sessionmaker(engine)
        async with sessionmaker() as session:
            count = (
                await session.execute(select(func.count()).select_from(User))
            ).scalar_one()
            if count > 0:
                logger.info("seed.skipped", users=count)
                return False
            session.add(
                User(
                    id=uuid.uuid4(),
                    email=E2E_ADMIN_EMAIL,
                    hashed_password=PasswordHelper().hash(E2E_ADMIN_PASSWORD),
                    is_active=True,
                    is_superuser=True,
                    is_verified=True,
                    display_name="E2E Admin",
                )
            )
            await session.commit()
            logger.info("seed.admin_created", email=E2E_ADMIN_EMAIL)
            return True
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
