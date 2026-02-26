"""
Seed script — creates default admin user and sample guardrail configs.
Run: python seed.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import async_session_maker, create_tables
from app.core.guardrail_catalog import GUARDRAIL_CATALOG
from app.core.security import hash_password
from app.models.user import User
from app.models.guardrail import GuardrailConfig
from sqlalchemy import select


SEED_GUARDRAILS = GUARDRAIL_CATALOG


async def seed():
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
                email="admin@project73.ai",
                hashed_password=hash_password("admin"),
                role="admin",
            )
            session.add(admin)
            await session.commit()
            print("Created admin user (username: admin, password: admin)")
        else:
            # Backfill full_name/email if missing
            if not existing_admin.full_name:
                existing_admin.full_name = "Administrator"
                existing_admin.email = "admin@project73.ai"
                await session.commit()
            print("Admin user already exists, skipping.")

        # Create normal user account
        result = await session.execute(select(User).where(User.username == "user"))
        existing_user = result.scalar_one_or_none()
        if not existing_user:
            normal_user = User(
                username="user",
                full_name="Demo User",
                email="user@project73.ai",
                hashed_password=hash_password("user123"),
                role="viewer",
            )
            session.add(normal_user)
            await session.commit()
            print("Created normal user (username: user, password: user123)")
        else:
            print("Normal user already exists, skipping.")

        # Keep viewer account for backward compatibility
        result = await session.execute(select(User).where(User.username == "viewer"))
        existing_viewer = result.scalar_one_or_none()
        if not existing_viewer:
            viewer = User(
                username="viewer",
                full_name="Viewer Account",
                email="viewer@project73.ai",
                hashed_password=hash_password("viewer123"),
                role="viewer",
            )
            session.add(viewer)
            await session.commit()
            print("Created viewer user (username: viewer, password: viewer123)")

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
