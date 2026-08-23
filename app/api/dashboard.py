"""
Direct CRUD routes for the /dashboard page: medicines, dosages, and
medical record metadata, plus a read-only appointments list.

DELIBERATELY SEPARATE from the agent/HITL path in app/api/chat.py: these
endpoints represent the user editing THEIR OWN data directly through a
form, not an AI agent proposing a change on their behalf. Because there's
no agent involved, there's no approval step to insert here -- the human
IS the one making the decision, in the same moment they make it, by
clicking Save. HITL exists specifically to govern agent decisions (see
app/agents/hitl.py's docstring); a person editing their own records isn't
that.

Appointments are the one exception: notice there's no create/update/
delete route for them here, only a read-only list. Scheduling always goes
through the Appointment Agent + HITL flow (app/agents/workers.py), by
design -- "schedule only if asked or given permission" is exactly the
kind of judgment call that flow exists for.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import csv
import io
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.schemas import DosageCreate, DosageUpdate, MedicineCreate, MedicineUpdate, RecordUpdate
from app.db.models import Appointment, Dosage, MedicalRecord, Medicine, User, MedicationLog
from app.db.session import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ==================== Medicines ====================

@router.get("/medicines")
async def list_medicines(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List this user's active medicines, each with its active dosages
    nested inside. `selectinload` eager-loads the dosages relationship in
    a second efficient query, rather than lazy-loading them one-by-one
    per medicine (which would be N+1 queries).
    """
    result = await db.execute(
        select(Medicine)
        .where(Medicine.user_id == user.id, Medicine.is_active == True)  # noqa: E712
        .options(selectinload(Medicine.dosages))
    )
    medicines = result.scalars().all()
    return [
        {
            "id": m.id, "name": m.name, "strength": m.strength, "notes": m.notes,
            "supply_count": m.supply_count, "refill_threshold": m.refill_threshold,
            "dosages": [
                {
                    "id": d.id, "amount": d.amount, "frequency": d.frequency, 
                    "time_of_day": d.time_of_day, "consumption_instructions": d.consumption_instructions
                }
                for d in m.dosages if d.is_active
            ],
        }
        for m in medicines
    ]


@router.post("/medicines")
async def create_medicine(payload: MedicineCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Directly create a medicine (no agent, no approval step -- see the
    module docstring above for why).
    """
    # 1. Mock Interaction Check (Phase 3 feature)
    # Get user's existing active medicines
    result = await db.execute(select(Medicine).where(Medicine.user_id == user.id, Medicine.is_active == True))
    existing_meds = [m.name.lower() for m in result.scalars().all()]
    
    warning = None
    new_med_lower = payload.name.lower()
    
    # Very basic static mock dictionary for demo purposes
    mock_interactions = {
        ("metformin", "insulin"): "Potential risk of hypoglycemia. Monitor blood sugar closely.",
        ("ibuprofen", "lisinopril"): "NSAIDs can reduce the effect of blood pressure medication and affect kidneys.",
        ("warfarin", "aspirin"): "Increased risk of bleeding."
    }
    
    for existing in existing_meds:
        pair1 = (new_med_lower, existing)
        pair2 = (existing, new_med_lower)
        if pair1 in mock_interactions:
            warning = mock_interactions[pair1]
            break
        elif pair2 in mock_interactions:
            warning = mock_interactions[pair2]
            break

    # 2. Add the medicine
    med = Medicine(user_id=user.id, name=payload.name, strength=payload.strength, notes=payload.notes, supply_count=payload.supply_count, refill_threshold=payload.refill_threshold)
    db.add(med)
    await db.commit()
    await db.refresh(med)
    return {
        "id": med.id, "name": med.name, "strength": med.strength, 
        "notes": med.notes, "supply_count": med.supply_count, 
        "refill_threshold": med.refill_threshold,
        "warning": warning
    }


# ==================== Export ====================

@router.get("/medicines/export")
async def export_medicines_csv(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Medicine).where(Medicine.user_id == user.id, Medicine.is_active == True).options(selectinload(Medicine.dosages))
    )
    medicines = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Medicine Name", "Strength", "Notes", "Supply Count", "Amount", "Frequency", "Time of Day", "Consumption Instructions"])
    
    for m in medicines:
        if m.dosages:
            for d in m.dosages:
                if d.is_active:
                    writer.writerow([m.name, m.strength or "", m.notes or "", m.supply_count or "", d.amount, d.frequency, d.time_of_day or "", d.consumption_instructions or ""])
        else:
            writer.writerow([m.name, m.strength or "", m.notes or "", m.supply_count or "", "", "", "", ""])

    output.seek(0)
    response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=medicines_export.csv"
    return response

# ==================== Wearable Sync (Mock) ====================

@router.post("/sync-wearable")
async def sync_wearable(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Mock endpoint to simulate syncing data from Apple Health / Fitbit."""
    import random
    hr_drop = random.randint(2, 6)
    
    # Create a notification with the mock insight
    db.add(Notification(
        user_id=user.id,
        notification_type="wearable_insight",
        title="Apple Health Sync Complete",
        body=f"Your average resting heart rate dropped by {hr_drop} bpm this week! Your consistent medication adherence is paying off.",
    ))
    await db.commit()
    
    return {"status": "success", "message": f"Heart rate improved by {hr_drop} bpm."}



@router.put("/medicines/{medicine_id}")
async def update_medicine(medicine_id: str, payload: MedicineUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Directly update a medicine's fields. The WHERE clause requires
    Medicine.user_id == user.id, so a user can never edit another user's
    medicine even if they somehow guessed its id.
    """
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.user_id == user.id))
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")
    # exclude_unset=True means only fields the client actually included in
    # the request body get applied -- omitted fields leave the existing
    # value untouched, rather than being overwritten with None.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(med, field, value)
    await db.commit()
    return {"id": med.id, "name": med.name, "strength": med.strength, "notes": med.notes}


@router.delete("/medicines/{medicine_id}")
async def delete_medicine(medicine_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Hard-delete a medicine. Its dosages are deleted automatically via
    the cascade relationship defined in app/db/models.py.
    """
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.user_id == user.id))
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")
    await db.delete(med)  # cascades to dosages
    await db.commit()
    return {"deleted": True, "id": medicine_id}


# ==================== Dosages ====================

@router.post("/dosages")
async def create_dosage(payload: DosageCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Directly create a dosage for one of the user's own medicines. First
    verifies the target medicine actually belongs to this user, so a
    dosage can't be attached to someone else's medicine_id.
    """
    med_result = await db.execute(select(Medicine).where(Medicine.id == payload.medicine_id, Medicine.user_id == user.id))
    if not med_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Medicine not found")

    dosage = Dosage(medicine_id=payload.medicine_id, amount=payload.amount, frequency=payload.frequency, time_of_day=payload.time_of_day, consumption_instructions=payload.consumption_instructions)
    db.add(dosage)
    await db.commit()
    await db.refresh(dosage)
    return {"id": dosage.id, "amount": dosage.amount, "frequency": dosage.frequency, "time_of_day": dosage.time_of_day, "consumption_instructions": dosage.consumption_instructions}


@router.put("/dosages/{dosage_id}")
async def update_dosage(dosage_id: str, payload: DosageUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Directly update a dosage. Joins through Medicine to verify
    ownership, since Dosage itself doesn't carry a user_id column
    directly -- ownership is derived through its parent medicine.
    """
    result = await db.execute(
        select(Dosage).join(Medicine).where(Dosage.id == dosage_id, Medicine.user_id == user.id)
    )
    dosage = result.scalar_one_or_none()
    if not dosage:
        raise HTTPException(status_code=404, detail="Dosage not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dosage, field, value)
    await db.commit()
    return {"id": dosage.id, "amount": dosage.amount, "frequency": dosage.frequency, "time_of_day": dosage.time_of_day}


@router.delete("/dosages/{dosage_id}")
async def delete_dosage(dosage_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Hard-delete a single dosage entry, without touching its parent medicine."""
    result = await db.execute(
        select(Dosage).join(Medicine).where(Dosage.id == dosage_id, Medicine.user_id == user.id)
    )
    dosage = result.scalar_one_or_none()
    if not dosage:
        raise HTTPException(status_code=404, detail="Dosage not found")
    await db.delete(dosage)
    await db.commit()
    return {"deleted": True, "id": dosage_id}


# ==================== Records (metadata update + delete; upload lives in app/api/records.py) ====================

@router.put("/records/{record_id}")
async def update_record(record_id: str, payload: RecordUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Edit a medical record's metadata (e.g. its record_type tag). Does
    NOT touch the underlying PDF file or its indexed chunks -- this is a
    metadata-only edit.
    """
    result = await db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id, MedicalRecord.user_id == user.id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    await db.commit()
    return {"id": record.id, "filename": record.filename, "record_type": record.record_type}


@router.delete("/records/{record_id}")
async def delete_record(record_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete a medical record: removes the DB row (cascading to its
    RecordChunk rows, so it also disappears from semantic search
    immediately), then removes the actual PDF file from disk.
    """
    import os

    result = await db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id, MedicalRecord.user_id == user.id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    file_path = record.file_path
    await db.delete(record)  # cascades to record_chunks
    await db.commit()

    # Delete the DB row first, then the file -- if the file delete fails
    # for some reason, we don't want to be left with an orphaned DB row
    # pointing at a file we couldn't clean up; better to have an orphaned
    # file on disk (harmless) than a broken reference in the database.
    if os.path.exists(file_path):
        os.remove(file_path)

    return {"deleted": True, "id": record_id}


# ==================== Appointments (read-only here; scheduling stays agent+HITL gated) ====================

@router.get("/appointments")
async def list_appointments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List this user's appointments. Read-only by design -- see the
    module docstring for why there's no create/update/delete here.
    """
    result = await db.execute(select(Appointment).where(Appointment.user_id == user.id).order_by(Appointment.scheduled_for.asc()))
    appts = result.scalars().all()
    return [
        {
            "id": a.id, "doctor_name": a.doctor_name, "specialty": a.specialty,
            "scheduled_for": a.scheduled_for.isoformat(), "status": a.status,
        }
        for a in appts
    ]


# ==================== Adherence ====================

from pydantic import BaseModel

class AdherenceCreate(BaseModel):
    dosage_id: str
    status: str = "taken"

@router.post("/adherence")
async def log_adherence(payload: AdherenceCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Verify dosage belongs to user
    result = await db.execute(select(Dosage).join(Medicine).where(Dosage.id == payload.dosage_id, Medicine.user_id == user.id))
    dosage = result.scalar_one_or_none()
    if not dosage:
        raise HTTPException(status_code=404, detail="Dosage not found")
    
    log = MedicationLog(user_id=user.id, medicine_id=dosage.medicine_id, dosage_id=dosage.id, status=payload.status)
    db.add(log)
    
    # Only deduct if taken
    if payload.status == "taken" and dosage.medicine.supply_count is not None and dosage.medicine.supply_count > 0:
        dosage.medicine.supply_count -= 1
        
    await db.commit()
    return {"status": "success", "taken_at": log.taken_at.isoformat()}

@router.get("/adherence")
async def get_adherence_logs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MedicationLog).where(MedicationLog.user_id == user.id).order_by(MedicationLog.taken_at.asc()))
    logs = result.scalars().all()
    return [{"id": l.id, "medicine_id": l.medicine_id, "dosage_id": l.dosage_id, "status": l.status, "taken_at": l.taken_at.isoformat()} for l in logs]

