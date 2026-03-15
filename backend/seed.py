"""
Seed script — creates the admin user and guardrail configs.
Run: python seed.py

The admin password is read from the ADMIN_PASSWORD env var (or .env file).
In production (DEBUG=false) the script refuses to run without it.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings
from app.core.database import async_session_maker, create_tables
from app.core.guardrail_catalog import GUARDRAIL_CATALOG
from app.core.security import hash_password
from app.models.user import User
from app.models.guardrail import GuardrailConfig
from sqlalchemy import select


SEED_GUARDRAILS = GUARDRAIL_CATALOG


async def seed():
    # Resolve admin password
    admin_password = settings.admin_password
    if not admin_password:
        if settings.debug:
            admin_password = "admin"
            print("WARNING: ADMIN_PASSWORD not set — using insecure default 'admin'. Set ADMIN_PASSWORD in .env for production.")
        else:
            print("ERROR: ADMIN_PASSWORD is not set. Add it to your .env file and re-run.")
            sys.exit(1)

    print("Creating tables...")
    await create_tables()

    async with async_session_maker() as session:
        # Create admin user
        result = await session.execute(select(User).where(User.username == "admin"))
        existing_admin = result.scalar_one_or_none()
        if not existing_admin:
            admin = User(
                username="admin",
                full_name="Administrator",
                email="admin@seraph.io",
                hashed_password=hash_password(admin_password),
                role="admin",
            )
            session.add(admin)
            await session.commit()
            print("Created admin user (username: admin)")
        else:
            if not existing_admin.full_name:
                existing_admin.full_name = "Administrator"
                existing_admin.email = "admin@seraph.io"
                await session.commit()
            print("Admin user already exists, skipping.")

        # Create guardrail configs — insert any missing (scanner_type, direction) pairs
        result = await session.execute(select(GuardrailConfig))
        existing = result.scalars().all()
        existing_keys = {(g.scanner_type, g.direction) for g in existing}
        added = 0
        for config in SEED_GUARDRAILS:
            key = (config["scanner_type"], config["direction"])
            if key not in existing_keys:
                session.add(GuardrailConfig(**config))
                added += 1
        if added:
            await session.commit()
            print(f"Added {added} new guardrail configs ({len(existing)} already existed).")
        else:
            print(f"All {len(existing)} guardrail configs already present.")

    print("Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
