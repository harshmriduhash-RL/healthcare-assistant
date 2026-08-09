"""
Central configuration for the whole application.

Every environment-driven value (database URLs, API keys, secrets, tunables)
lives here in ONE place, so no other file ever reads `os.environ` directly.
Values are loaded from a `.env` file in the project root (see `.env.example`
for the template) via pydantic-settings, which also validates types (e.g.
`jwt_expire_minutes` must actually be an int) and falls back to the defaults
below if a variable isn't set.

Usage elsewhere in the codebase:
    from app.core.config import settings
    settings.groq_api_key
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Tells pydantic-settings to (a) read variables from a file named ".env"
    # in the working directory, and (b) ignore any extra/unknown env vars
    # instead of raising an error for them.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database ---
    # Two URLs because we use two different drivers for two different jobs:
    #   database_url       - "postgresql+asyncpg://..." used by SQLAlchemy's
    #                         ASYNC engine (app/db/session.py) for normal
    #                         request-handling queries.
    #   database_url_sync  - plain "postgresql://..." (psycopg2) used by
    #                         Alembic migrations and LangGraph's Postgres
    #                         checkpointer, neither of which use asyncpg.
    database_url: str = "postgresql+asyncpg://healthcare_user:changeme@localhost:5432/healthcare_ai"
    database_url_sync: str = "postgresql://healthcare_user:changeme@localhost:5432/healthcare_ai"

    # --- Groq (the LLM provider used for every agent call) ---
    groq_api_key: str = ""
    # Three separate model settings so each part of the system can use a
    # model sized for its job: the supervisor and workers need strong
    # reasoning for routing/structured-output decisions, while the
    # guardrail classifier just needs to be FAST since it runs on every
    # single message before anything else happens.
    groq_model_supervisor: str = "llama-3.3-70b-versatile"
    groq_model_worker: str = "llama-3.3-70b-versatile"
    groq_model_guardrail: str = "llama-3.1-8b-instant"

    # --- Auth ---
    jwt_secret_key: str = "dev-secret-change-me"  # MUST be overridden in production via .env
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # --- App ---
    app_env: str = "development"
    upload_dir: str = "uploads/medical_records"  # where uploaded PDF files are saved on disk
    max_upload_mb: int = 15  # reject uploads larger than this (see app/api/records.py)


# A single shared instance, constructed once when this module is first
# imported. Every other file imports THIS object rather than constructing
# its own Settings(), so the whole app reads consistent configuration.
settings = Settings()
