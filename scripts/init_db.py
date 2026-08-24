"""
Database setup script for CarePilot AI: creates pgvector extension and all tables.

Run with: python -m scripts.init_db [--reset]
"""

import asyncio
import sys
from sqlalchemy import text

from app.db.models import *  # noqa: F401, F403
from app.db.session import Base, engine


async def main():
    reset = "--reset" in sys.argv
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        if reset:
            print("Resetting database tables...")
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized successfully: pgvector extension + all tables ready.")


if __name__ == "__main__":
    asyncio.run(main())
