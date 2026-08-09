"""
Quick one-shot database setup: creates the pgvector extension and every
table defined in app/db/models.py directly from the ORM models.

Run once with:  python -m scripts.init_db

This is a FALLBACK, kept for convenience -- the primary, recommended way
to set up (and evolve) the schema is Alembic migrations:
    alembic upgrade head
The difference: this script's Base.metadata.create_all() has no concept
of migration HISTORY -- it can create tables that don't exist yet, but
it can't apply incremental changes to tables that already exist (e.g.
adding a column later), and it leaves no record of what changed when.
Alembic (see migrations/) tracks that history properly. Use this script
only for a fast first-time local setup or in a throwaway environment.
"""

import asyncio

from sqlalchemy import text

from app.db.models import *  # noqa: F401,F403 - imports every model class so they register themselves on Base.metadata; without this import, create_all() below wouldn't know these tables exist
from app.db.session import Base, engine


async def main():
    async with engine.begin() as conn:
        # pgvector must exist before SQLAlchemy tries to create the
        # record_chunks table, since its `embedding` column uses the
        # Vector type that extension provides.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # create_all() looks at every model class that inherited from Base
        # (which happened via the `import *` above) and issues
        # "CREATE TABLE IF NOT EXISTS" for each one that doesn't already exist.
        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized: pgvector extension + all tables created.")


if __name__ == "__main__":
    asyncio.run(main())
