"""
Alembic's environment script -- runs every time `alembic upgrade/downgrade/
revision` is invoked. This is boilerplate Alembic generates automatically
(`alembic init migrations`), edited here to:
  1. Read the database URL from OUR OWN app settings (.env), instead of
     from alembic.ini, so there's exactly one place the DB connection is
     configured for the whole project.
  2. Point at our SQLAlchemy models (app/db/models.py) as the source of
     truth for `alembic revision --autogenerate` to diff against.
  3. Ensure the pgvector extension exists before any migration runs,
     since our schema includes a Vector column (record_chunks.embedding).
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

# Make "app.*" importable when alembic is run from the project root
# (alembic runs this file directly, so it doesn't automatically have the
# project root on sys.path the way `uvicorn app.main:app` does).
import os
import sys
sys.path.insert(0, os.getcwd())

from app.core.config import settings
from app.db.session import Base
from app.db import models  # noqa: F401 - importing this registers every model class on Base.metadata, which target_metadata below needs

config = context.config

# Overrides whatever's in alembic.ini with the sync DB URL from our own
# app settings/.env -- so .env stays the single source of truth for the
# database connection instead of duplicating it in alembic.ini too.
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata is what `alembic revision --autogenerate` compares
# against the live database to detect schema changes -- it needs to be
# OUR models' metadata (via Base, imported from app/db/session.py) for
# autogenerate to work correctly against this project's schema.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate migration SQL without a live DB connection (used by
    `alembic upgrade head --sql`, which just prints SQL instead of
    running it). Not used in this project's normal workflow, but kept
    since it's part of Alembic's standard template.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """The normal path: connect to the real database and actually apply
    migrations. This is what runs for `alembic upgrade head`.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # migrations are a one-shot operation, no need to keep a connection pool around after
    )

    with connectable.connect() as connection:
        # pgvector must exist before any table with a Vector column
        # (record_chunks) is created -- done here, outside the migration
        # files themselves, so it's guaranteed to run before EVERY
        # migration, not just the first one, in case this environment
        # script ever runs against a fresh database that skipped it.
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()

        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


# Alembic calls this script with is_offline_mode() already decided based
# on how it was invoked -- this dispatches to the matching function above.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
