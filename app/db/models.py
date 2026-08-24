"""
The entire database schema for CarePilot AI, defined as SQLAlchemy ORM models.

Every table in the system is a class here. This file is the single source
of truth for the schema. CarePilot AI operates around the `Patient` entity,
managed by one or more `User` (Caregiver) accounts via `CaregiverPatient` links.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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
    """Default value generator for primary keys: a random UUID4 as a string."""
    return str(uuid.uuid4())


class User(Base):
    """A registered account (Caregiver).

    A Caregiver signs up, owns an account, and manages one or more Patients
    via `caregiver_patient` links with assigned roles (primary, secondary, viewer).
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Caregiver-patient relationships
    caregiver_links: Mapped[list["CaregiverPatient"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Patient(Base):
    """An aging parent being watched over by CarePilot AI.

    Patients do not log into the app or install software. They receive daily
    touchpoints over WhatsApp / phone calls, and their data is managed by
    linked Caregivers.
    """
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    age_or_dob: Mapped[str] = mapped_column(String(50), nullable=True)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=True)  # e.g., "Mother", "Father"
    phone_number: Mapped[str] = mapped_column(String(30), nullable=True, index=True)
    primary_language: Mapped[str] = mapped_column(String(50), default="Hindi")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    abdm_id: Mapped[str] = mapped_column(String(50), nullable=True)  # India ABHA Health ID
    emergency_contact_phone: Mapped[str] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    caregiver_links: Mapped[list["CaregiverPatient"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    medicines: Mapped[list["Medicine"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    records: Mapped[list["MedicalRecord"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    check_ins: Mapped[list["PatientCheckIn"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    alerts: Mapped[list["PatientAlert"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    vitals: Mapped[list["VitalsLog"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    family_tasks: Mapped[list["FamilyTask"]] = relationship(back_populates="patient", cascade="all, delete-orphan")


class CaregiverPatient(Base):
    """Join table linking Caregivers (Users) to Patients with specific roles and access tokens."""
    __tablename__ = "caregiver_patient"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default="primary")  # primary | secondary | viewer
    share_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=gen_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="caregiver_links")
    patient: Mapped["Patient"] = relationship(back_populates="caregiver_links")


class Medicine(Base):
    """One medicine a patient is taking."""
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    strength: Mapped[str] = mapped_column(String(50), nullable=True)  # e.g., "500mg"
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    supply_count: Mapped[int] = mapped_column(Integer, nullable=True)
    refill_threshold: Mapped[int] = mapped_column(Integer, server_default="10")
    monthly_cost_inr: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    generic_substitute: Mapped[str] = mapped_column(String(255), nullable=True)
    generic_savings_inr: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_streak: Mapped[int] = mapped_column(Integer, server_default="0")
    longest_streak: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="medicines")
    dosages: Mapped[list["Dosage"]] = relationship(back_populates="medicine", cascade="all, delete-orphan")


class Dosage(Base):
    """A dosing schedule for one medicine."""
    __tablename__ = "dosages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    medicine_id: Mapped[str] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[str] = mapped_column(String(50), nullable=False)
    frequency: Mapped[str] = mapped_column(String(100), nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(100), nullable=True)  # e.g. "08:00,20:00"
    consumption_instructions: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    medicine: Mapped["Medicine"] = relationship(back_populates="dosages")


class MedicationLog(Base):
    """Tracks each individual time a dose is marked as taken/missed."""
    __tablename__ = "medication_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    medicine_id: Mapped[str] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False, index=True)
    dosage_id: Mapped[str] = mapped_column(ForeignKey("dosages.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="taken")  # taken | missed | skipped
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    medicine: Mapped["Medicine"] = relationship()
    dosage: Mapped["Dosage"] = relationship()


class MedicalRecord(Base):
    """Metadata for uploaded lab reports, prescriptions, or medical documents."""
    __tablename__ = "medical_records"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    record_type: Mapped[str] = mapped_column(String(100), nullable=True)
    extracted_summary: Mapped[str] = mapped_column(Text, nullable=True)
    reconciliation_proposed: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="records")
    chunks: Mapped[list["RecordChunk"]] = relationship(back_populates="record", cascade="all, delete-orphan")


class RecordChunk(Base):
    """Text chunks and embeddings from uploaded medical records for RAG search."""
    __tablename__ = "record_chunks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    record_id: Mapped[str] = mapped_column(ForeignKey("medical_records.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=True)

    record: Mapped["MedicalRecord"] = relationship(back_populates="chunks")


class Appointment(Base):
    """Doctor appointments for a patient."""
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    doctor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(String(255), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="proposed")  # proposed | confirmed | cancelled
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="appointments")


class PatientCheckIn(Base):
    """Daily health check-in touchpoints sent to the patient and their responses."""
    __tablename__ = "patient_check_ins"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    channel: Mapped[str] = mapped_column(String(50), default="whatsapp_voice")  # whatsapp_voice | whatsapp_text | ivr_call | app
    status: Mapped[str] = mapped_column(String(50), default="no_response")  # taken | missed | unclear | no_response
    transcript: Mapped[str] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str] = mapped_column(String(500), nullable=True)
    raw_response: Mapped[str] = mapped_column(Text, nullable=True)
    dose_details: Mapped[dict] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="check_ins")


class PatientAlert(Base):
    """Pattern intelligence alerts fired for caregivers when anomalies occur."""
    __tablename__ = "patient_alerts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info | warning | critical
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(100), nullable=False)  # missed_checkins | vitals_trend | checkin_gap | polypharmacy | drug_interaction | fall_detection
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="alerts")


class VitalsLog(Base):
    """Time-series vitals & lab values logged for a patient."""
    __tablename__ = "vitals_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    vital_type: Mapped[str] = mapped_column(String(50), nullable=False)  # bp_sys | bp_dia | hr | glucose | hba1c | creatinine | cholesterol | weight
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")  # wearable | manual | lab_report
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    patient: Mapped["Patient"] = relationship(back_populates="vitals")


class FamilyTask(Base):
    """Shared family care tasks between caregivers managing the same patient."""
    __tablename__ = "family_tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    assigned_to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending | completed
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="family_tasks")


class AgentAuditLog(Base):
    """Audit log of agent executions, proposals, and HITL decisions."""
    __tablename__ = "agent_audit_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)  # propose | approve | reject | execute | guardrail_block
    payload: Mapped[dict] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """Caregiver reminders and digest notifications."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)  # dosage_due | appointment_upcoming | low_supply | alert_escalation
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=True)
    related_id: Mapped[str] = mapped_column(String(255), nullable=True)
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
