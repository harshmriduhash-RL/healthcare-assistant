"""
Direct CRUD routes for the dashboard: medicines, dosages, records metadata, appointments list, and adherence.
All operations are scoped to active Patient context via `get_current_patient_context`.
"""

import csv
import io
import random
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_patient_context, get_current_user
from app.core.schemas import DosageCreate, DosageUpdate, MedicineCreate, MedicineUpdate, RecordUpdate
from app.db.models import Appointment, Dosage, MedicalRecord, MedicationLog, Medicine, Notification, Patient, User
from app.db.session import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ==================== Medicines ====================

@router.get("/medicines")
async def list_medicines(
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List medicines for current patient context."""
    result = await db.execute(
        select(Medicine)
        .where(Medicine.patient_id == patient.id, Medicine.is_active == True)
        .options(selectinload(Medicine.dosages))
    )
    medicines = result.scalars().all()
    return [
        {
            "id": m.id, "name": m.name, "strength": m.strength, "notes": m.notes,
            "supply_count": m.supply_count, "refill_threshold": m.refill_threshold,
            "current_streak": m.current_streak, "longest_streak": m.longest_streak,
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
async def create_medicine(
    payload: MedicineCreate,
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Directly create a medicine for current patient."""
    med = Medicine(
        patient_id=patient.id,
        user_id=user.id,
        name=payload.name,
        strength=payload.strength,
        notes=payload.notes,
        supply_count=payload.supply_count,
        refill_threshold=payload.refill_threshold,
    )
    db.add(med)
    await db.commit()
    await db.refresh(med)
    return {
        "id": med.id, "name": med.name, "strength": med.strength,
        "notes": med.notes, "supply_count": med.supply_count,
        "refill_threshold": med.refill_threshold,
    }


@router.put("/medicines/{medicine_id}")
async def update_medicine(
    medicine_id: str,
    payload: MedicineUpdate,
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.patient_id == patient.id))
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(med, field, value)
    await db.commit()
    return {"id": med.id, "name": med.name, "strength": med.strength, "notes": med.notes}


@router.delete("/medicines/{medicine_id}")
async def delete_medicine(
    medicine_id: str,
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.patient_id == patient.id))
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")
    await db.delete(med)
    await db.commit()
    return {"deleted": True, "id": medicine_id}


# ==================== Dosages ====================

@router.post("/dosages")
async def create_dosage(
    payload: DosageCreate,
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    med_result = await db.execute(select(Medicine).where(Medicine.id == payload.medicine_id, Medicine.patient_id == patient.id))
    if not med_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Medicine not found")

    dosage = Dosage(
        medicine_id=payload.medicine_id,
        amount=payload.amount,
        frequency=payload.frequency,
        time_of_day=payload.time_of_day,
        consumption_instructions=payload.consumption_instructions,
    )
    db.add(dosage)
    await db.commit()
    await db.refresh(dosage)
    return {
        "id": dosage.id, "amount": dosage.amount, "frequency": dosage.frequency,
        "time_of_day": dosage.time_of_day, "consumption_instructions": dosage.consumption_instructions,
    }


@router.put("/dosages/{dosage_id}")
async def update_dosage(
    dosage_id: str,
    payload: DosageUpdate,
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dosage).join(Medicine).where(Dosage.id == dosage_id, Medicine.patient_id == patient.id)
    )
    dosage = result.scalar_one_or_none()
    if not dosage:
        raise HTTPException(status_code=404, detail="Dosage not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dosage, field, value)
    await db.commit()
    return {"id": dosage.id, "amount": dosage.amount, "frequency": dosage.frequency, "time_of_day": dosage.time_of_day}


@router.delete("/dosages/{dosage_id}")
async def delete_dosage(
    dosage_id: str,
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dosage).join(Medicine).where(Dosage.id == dosage_id, Medicine.patient_id == patient.id)
    )
    dosage = result.scalar_one_or_none()
    if not dosage:
        raise HTTPException(status_code=404, detail="Dosage not found")
    await db.delete(dosage)
    await db.commit()
    return {"deleted": True, "id": dosage_id}


# ==================== Appointments ====================

@router.get("/appointments")
async def list_appointments(
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Appointment)
        .where(Appointment.patient_id == patient.id)
        .order_by(Appointment.scheduled_for.asc())
    )
    appts = result.scalars().all()
    return [
        {
            "id": a.id, "doctor_name": a.doctor_name, "specialty": a.specialty,
            "scheduled_for": a.scheduled_for.isoformat(), "status": a.status,
        }
        for a in appts
    ]


# ==================== Export ====================

@router.get("/medicines/export")
async def export_medicines_csv(
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Medicine).where(Medicine.patient_id == patient.id, Medicine.is_active == True).options(selectinload(Medicine.dosages))
    )
    medicines = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Medicine Name", "Strength", "Notes", "Supply Count", "Amount", "Frequency", "Time of Day", "Instructions"])

    for m in medicines:
        if m.dosages:
            for d in m.dosages:
                if d.is_active:
                    writer.writerow([m.name, m.strength or "", m.notes or "", m.supply_count or "", d.amount, d.frequency, d.time_of_day or "", d.consumption_instructions or ""])
        else:
            writer.writerow([m.name, m.strength or "", m.notes or "", m.supply_count or "", "", "", "", ""])

    output.seek(0)
    response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={patient.name.replace(' ', '_')}_medicines.csv"
    return response
