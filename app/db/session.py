"""
SQLAlchemy async database setup: the engine (connection pool) and the
session factory every request uses to talk to Postgres.

Nothing outside this file constructs an engine or session directly --
routes get a session via the get_db() dependency below, and background
jobs (scheduler, RAG indexing) use AsyncSessionLocal() directly since
they run outside a request context.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# The engine manages a pool of actual database connections. `echo=False`
# keeps SQLAlchemy from printing every generated SQL statement to the
# console (flip to True temporarily if you need to debug a query).
engine = create_async_engine(settings.database_url, echo=False, future=True)

# A factory that produces new AsyncSession objects. expire_on_commit=False
# means objects we've loaded stay usable (their attributes stay readable)
# after a commit(), instead of SQLAlchemy forcing a fresh DB round-trip to
# re-fetch them the next time they're accessed -- convenient for our
# pattern of "create row, commit, then read its fields back to return as JSON."
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """The base class every ORM model (see app/db/models.py) inherits from.
    SQLAlchemy uses Base.metadata to know the full set of tables that
    exist -- this is what scripts/init_db.py's create_all() and Alembic's
    autogenerate both read from.
    """
    pass


async def get_db():
    """FastAPI dependency: yields one AsyncSession per request.

    Using `async with` guarantees the session is closed (connection
    returned to the pool) once the request finishes, whether it succeeded
    or raised an exception. Routes declare `db: AsyncSession = Depends(get_db)`
    to get one of these automatically.
    """
    async with AsyncSessionLocal() as session:
        yield session
