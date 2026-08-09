"""
The entire database schema, defined as SQLAlchemy ORM models.

Every table in the system is a class here. This file is the single
source of truth for the schema -- Alembic's migrations (migrations/versions/)
are generated FROM these models (or, in this prototype, hand-written to
match them), and scripts/init_db.py builds tables directly from them too.

Every user-owned table (Medicine, MedicalRecord, Appointment, etc.) carries
a `user_id` foreign key with `ondelete="CASCADE"` -- this is what makes
"multi-user, each person only sees their own data" actually enforced at
the database level, not just in application code: deleting a user
automatically cleans up everything that belonged to them.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def gen_uuid() -> str:
    """Default value generator for primary keys: a random UUID4 as a string.

    We generate ids in Python (rather than relying on a Postgres default
    like gen_random_uuid()) so a newly-constructed-but-not-yet-committed
    ORM object already has a usable `.id` -- handy when we need to
    reference it (e.g. in a proposed_action payload) before calling commit().
    """
    return str(uuid.uuid4())


class User(Base):
    """A registered account. Every other table's data ultimately traces
    back to exactly one User via a user_id foreign key.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    # Deliberately kept minimal per product decision: username + password
    # only -- no email verification, OTP, or third-party auth (Google,
    # etc). Simpler signup/login at the cost of no "forgot password" email
    # recovery flow, which is an acceptable tradeoff for this prototype.
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    # Only ever a bcrypt hash (see app/core/security.py) -- never plaintext.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # `relationship(...)` fields aren't real columns -- they let SQLAlchemy
    # load related rows conveniently (e.g. `user.medicines`) and, via
    # cascade="all, delete-orphan", make deleting a User also delete
    # everything they own in Python-land (in addition to the DB-level
    # ON DELETE CASCADE on the foreign keys below).
    medicines: Mapped[list["Medicine"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    records: Mapped[list["MedicalRecord"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Medicine(Base):
    """One medicine a user is (or was) taking. Dosage schedules live
    separately in the Dosage table below, since one medicine can have
    multiple dosage entries over time (e.g. dose changed by a doctor).
    """
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    strength: Mapped[str] = mapped_column(String(50), nullable=True)  # free text, e.g. "500mg"
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    # Soft-delete flag: "remove_medicine" (see app/mcp_servers/postgres_tools.py)
    # currently hard-deletes the row rather than using this flag, but it's
    # kept for future use (e.g. "discontinued but keep for history").
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="medicines")
    dosages: Mapped[list["Dosage"]] = relationship(back_populates="medicine", cascade="all, delete-orphan")


class Dosage(Base):
    """A dosing schedule for one medicine -- how much, how often, and at
    what time(s) of day. `time_of_day` is a simple comma-separated string
    of "HH:MM" values (e.g. "08:00,20:00") rather than a separate table,
    since the prototype's reminder scheduler (app/core/scheduler.py) just
    needs to string-match against the current clock time.
    """
    __tablename__ = "dosages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    medicine_id: Mapped[str] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "5mg", "1 tablet"
    frequency: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "daily", "twice a day"
    time_of_day: Mapped[str] = mapped_column(String(100), nullable=True)  # e.g. "08:00,20:00"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    medicine: Mapped["Medicine"] = relationship(back_populates="dosages")


class MedicalRecord(Base):
    """Metadata for one uploaded PDF (lab report, prescription, etc.).
    The actual PDF bytes live on disk at `file_path` -- this row just
    tracks where it is and what it is. The extracted/embedded TEXT content
    lives separately in RecordChunk rows below, one row per PDF "chunk."
    """
    __tablename__ = "medical_records"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)  # original filename as uploaded
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)  # where it's actually stored on disk
    record_type: Mapped[str] = mapped_column(String(100), nullable=True)  # e.g. lab_report, prescription
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="records")

    # cascade="all, delete-orphan" here means deleting a MedicalRecord row
    # (see app/api/dashboard.py's delete_record) automatically deletes all
    # of its RecordChunk rows too -- we don't have to delete them by hand.
    chunks: Mapped[list["RecordChunk"]] = relationship(back_populates="record", cascade="all, delete-orphan")


class RecordChunk(Base):
    """One chunk of extracted text from a medical record PDF, plus its
    vector embedding, for semantic (similarity) search.

    Why chunks instead of storing the whole PDF's text as one row: LLMs
    and embedding models work best over a few hundred words at a time, and
    chunking lets the Records Agent (app/agents/workers.py) retrieve just
    the most RELEVANT few paragraphs for a question instead of the whole
    document. See app/agents/rag.py for how these get created and queried.
    """
    __tablename__ = "record_chunks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    record_id: Mapped[str] = mapped_column(ForeignKey("medical_records.id", ondelete="CASCADE"), nullable=False, index=True)
    # Duplicated from the parent MedicalRecord for query convenience: lets
    # semantic search filter "only this user's chunks" directly, without
    # having to join back to medical_records on every search query.
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # this chunk's position within the original document
    content: Mapped[str] = mapped_column(Text, nullable=False)  # the actual extracted text for this chunk
    # 384-dim vector because that's the output size of the
    # "all-MiniLM-L6-v2" sentence-transformers model used in app/agents/rag.py.
    # If that embedding model ever changes, this dimension has to change
    # (and the table re-embedded) to match.
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=True)

    record: Mapped["MedicalRecord"] = relationship(back_populates="chunks")


class Appointment(Base):
    """A scheduled (or proposed) doctor appointment. Written to only via
    the Appointment Agent + human approval flow (see app/agents/workers.py
    and app/agents/graph.py) -- there's no direct-dashboard-edit path for
    appointments by design (see the README, section 4, for why).
    """
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(String(255), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # "proposed" (not yet approved), "confirmed" (approved + written), or
    # "cancelled". In the current flow, schedule_appointment() in
    # postgres_tools.py only ever creates rows already as "confirmed"
    # (since by the time that tool runs, a human has already approved it) --
    # "proposed" exists for potential future use (e.g. saving a draft
    # before approval, rather than only holding it in graph state).
    status: Mapped[str] = mapped_column(String(50), default="proposed")
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="appointments")


class AgentAuditLog(Base):
    """Every agent action + HITL decision, for observability and the
    demo trace view. See app/core/observability.py for the write helpers,
    and the GET /api/chat/trace/{thread_id} route in app/api/chat.py for
    how these rows get read back out and shown in the UI.
    """
    __tablename__ = "agent_audit_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Groups all the log rows belonging to one conversation together --
    # matches the LangGraph checkpointer's thread_id, so a single
    # conversation's full trace (guardrail check -> routing -> proposal ->
    # human decision -> execution) can be pulled with one query.
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)  # propose, approve, reject, execute, guardrail_block
    payload: Mapped[dict] = mapped_column(JSONB, nullable=True)  # whatever structured detail is relevant to this event
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)  # how long this step took, if measured
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """Reminders produced by the background scheduler (dosages due, upcoming
    appointments). See app/core/scheduler.py for what creates these.

    The scheduler only ever writes rows here -- it never calls a write tool
    on medicines/dosages/appointments directly. Any action a person wants
    to take in response to a reminder still goes through the normal agent +
    HITL flow (e.g. they'd have to go to chat and ask the assistant to
    reschedule, which is then subject to approval like anything else).
    """
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)  # dosage_due, appointment_upcoming
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=True)
    related_id: Mapped[str] = mapped_column(String(255), nullable=True)  # the dosage_id or appointment_id this reminder is about
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
