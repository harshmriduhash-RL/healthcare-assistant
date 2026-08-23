from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.core.deps import get_current_user
from app.db.models import User, Medicine, Appointment, MedicalRecord, MedicationLog
from app.db.session import get_db

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

@router.get("/")
async def get_timeline(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Fetch all major health events for this user and return them sorted chronologically."""
    events = []

    # 1. Medicines added
    result = await db.execute(select(Medicine).where(Medicine.user_id == user.id))
    for m in result.scalars().all():
        events.append({
            "type": "medicine_added",
            "title": f"Started {m.name} {m.strength or ''}",
            "description": f"Supply: {m.supply_count or 'N/A'}",
            "timestamp": m.created_at.isoformat() if m.created_at else None
        })

    # 2. Appointments scheduled
    result = await db.execute(select(Appointment).where(Appointment.user_id == user.id))
    for a in result.scalars().all():
        events.append({
            "type": "appointment_scheduled",
            "title": f"Appointment with {a.doctor_name}",
            "description": a.specialty or "General",
            "timestamp": a.created_at.isoformat() if a.created_at else None,
            "scheduled_for": a.scheduled_for.isoformat() if a.scheduled_for else None
        })

    # 3. Medical records uploaded
    result = await db.execute(select(MedicalRecord).where(MedicalRecord.user_id == user.id))
    for r in result.scalars().all():
        events.append({
            "type": "record_uploaded",
            "title": f"Uploaded {r.record_type or 'document'}",
            "description": r.filename,
            "timestamp": r.uploaded_at.isoformat() if r.uploaded_at else None
        })

    # 4. Medication logs (Adherence)
    result = await db.execute(select(MedicationLog, Medicine).join(Medicine, MedicationLog.medicine_id == Medicine.id).where(MedicationLog.user_id == user.id))
    for log, med in result.all():
        events.append({
            "type": "medication_log",
            "title": f"{'Took' if log.status == 'taken' else 'Missed'} {med.name}",
            "description": f"Dose marked as {log.status}",
            "timestamp": log.taken_at.isoformat() if log.taken_at else None
        })

    # Filter out events without timestamp and sort descending (newest first)
    events = [e for e in events if e.get("timestamp")]
    events.sort(key=lambda x: x["timestamp"], reverse=True)

    return events


@router.get("/public/{username}")
async def get_public_timeline(username: str, db: AsyncSession = Depends(get_db)):
    """Caregiver / Family view: Read-only access to a patient's timeline by username."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    
    if not user:
        return []

    # Re-use the same logic as above
    events = []

    # 1. Medicines added
    med_res = await db.execute(select(Medicine).where(Medicine.user_id == user.id))
    for m in med_res.scalars().all():
        events.append({
            "type": "medicine_added",
            "title": f"Started {m.name} {m.strength or ''}",
            "description": f"Supply: {m.supply_count or 'N/A'}",
            "timestamp": m.created_at.isoformat() if m.created_at else None
        })

    # 2. Appointments scheduled
    appt_res = await db.execute(select(Appointment).where(Appointment.user_id == user.id))
    for a in appt_res.scalars().all():
        events.append({
            "type": "appointment_scheduled",
            "title": f"Appointment with {a.doctor_name}",
            "description": a.specialty or "General",
            "timestamp": a.created_at.isoformat() if a.created_at else None,
            "scheduled_for": a.scheduled_for.isoformat() if a.scheduled_for else None
        })

    # 3. Medical records uploaded
    rec_res = await db.execute(select(MedicalRecord).where(MedicalRecord.user_id == user.id))
    for r in rec_res.scalars().all():
        events.append({
            "type": "record_uploaded",
            "title": f"Uploaded {r.record_type or 'document'}",
            "description": r.filename,
            "timestamp": r.uploaded_at.isoformat() if r.uploaded_at else None
        })

    # 4. Medication logs (Adherence)
    log_res = await db.execute(select(MedicationLog, Medicine).join(Medicine, MedicationLog.medicine_id == Medicine.id).where(MedicationLog.user_id == user.id))
    for log, med in log_res.all():
        events.append({
            "type": "medication_log",
            "title": f"{'Took' if log.status == 'taken' else 'Missed'} {med.name}",
            "description": f"Dose marked as {log.status}",
            "timestamp": log.taken_at.isoformat() if log.taken_at else None
        })

    events = [e for e in events if e.get("timestamp")]
    events.sort(key=lambda x: x["timestamp"], reverse=True)

    return events
