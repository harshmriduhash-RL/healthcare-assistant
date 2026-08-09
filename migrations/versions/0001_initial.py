"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-09

Creates the entire initial database schema in one migration: users,
medicines, dosages, medical_records, record_chunks (with a pgvector
column + IVFFlat similarity index), appointments, and agent_audit_log.

This migration was hand-written to mirror app/db/models.py exactly,
rather than generated via `alembic revision --autogenerate` against a
live database (none was available in the environment this was built in).
Before relying on this in a real environment, it's worth running
`alembic upgrade head` followed by `alembic revision --autogenerate` once
against a fresh database to confirm Alembic detects zero drift between
this migration and the ORM models.

upgrade() creates every table (and the vector extension); downgrade()
tears them all back down in reverse dependency order (children before
parents, respecting foreign keys).
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "medicines",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("strength", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_medicines_user_id", "medicines", ["user_id"])

    op.create_table(
        "dosages",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("medicine_id", UUID(as_uuid=False), sa.ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.String(50), nullable=False),
        sa.Column("frequency", sa.String(100), nullable=False),
        sa.Column("time_of_day", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_dosages_medicine_id", "dosages", ["medicine_id"])

    op.create_table(
        "medical_records",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("record_type", sa.String(100), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_medical_records_user_id", "medical_records", ["user_id"])

    op.create_table(
        "record_chunks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("record_id", UUID(as_uuid=False), sa.ForeignKey("medical_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(384), nullable=True),
    )
    op.create_index("ix_record_chunks_record_id", "record_chunks", ["record_id"])
    op.create_index("ix_record_chunks_user_id", "record_chunks", ["user_id"])
    # IVFFlat index for cosine-distance ANN search; safe to create even before rows exist.
    op.execute(
        "CREATE INDEX ix_record_chunks_embedding ON record_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "appointments",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doctor_name", sa.String(255), nullable=False),
        sa.Column("specialty", sa.String(255), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(50), server_default="proposed"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_appointments_user_id", "appointments", ["user_id"])

    op.create_table(
        "agent_audit_log",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(255), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_audit_log_user_id", "agent_audit_log", ["user_id"])
    op.create_index("ix_agent_audit_log_thread_id", "agent_audit_log", ["thread_id"])


def downgrade() -> None:
    op.drop_table("agent_audit_log")
    op.drop_table("appointments")
    op.execute("DROP INDEX IF EXISTS ix_record_chunks_embedding")
    op.drop_table("record_chunks")
    op.drop_table("medical_records")
    op.drop_table("dosages")
    op.drop_table("medicines")
    op.drop_table("users")
