"""
MCP-style tool layer: Database write actions for medicines, dosages, appointments, refills, and reconciliation.
Every function in this file is executed ONLY AFTER explicit human approval (HITL).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Dosage, Medicine


async def add_medicine(db: AsyncSession, patient_id: str, user_id: str, name: str, strength: str | None, notes: str | None) -> dict:
    """Insert a new Medicine row for a patient."""
    med = Medicine(patient_id=patient_id, user_id=user_id, name=name, strength=strength, notes=notes)
    db.add(med)
    await db.commit()
    await db.refresh(med)
    return {"id": med.id, "name": med.name, "strength": med.strength}


async def update_medicine(db: AsyncSession, patient_id: str, medicine_id: str, **fields) -> dict:
    """Update an existing medicine's fields."""
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.patient_id == patient_id))
    med = result.scalar_one_or_none()
    if not med:
        return {"error": "Medicine not found"}
    for key, value in fields.items():
        if hasattr(med, key) and value is not None:
            setattr(med, key, value)
    await db.commit()
    return {"id": med.id, "name": med.name, "updated": True}


async def remove_medicine(db: AsyncSession, patient_id: str, medicine_id: str) -> dict:
    """Hard-delete a medicine."""
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.patient_id == patient_id))
    med = result.scalar_one_or_none()
    if not med:
        return {"error": "Medicine not found"}
    await db.delete(med)
    await db.commit()
    return {"deleted": True, "id": medicine_id}


async def add_dosage(db: AsyncSession, medicine_id: str, amount: str, frequency: str, time_of_day: str | None) -> dict:
    """Insert a new Dosage row linked to a medicine."""
    dosage = Dosage(medicine_id=medicine_id, amount=amount, frequency=frequency, time_of_day=time_of_day)
    db.add(dosage)
    await db.commit()
    await db.refresh(dosage)
    return {"id": dosage.id, "amount": dosage.amount, "frequency": dosage.frequency}


async def update_dosage(db: AsyncSession, dosage_id: str, **fields) -> dict:
    """Update an existing dosage's fields."""
    result = await db.execute(select(Dosage).where(Dosage.id == dosage_id))
    dosage = result.scalar_one_or_none()
    if not dosage:
        return {"error": "Dosage not found"}
    for key, value in fields.items():
        if hasattr(dosage, key) and value is not None:
            setattr(dosage, key, value)
    await db.commit()
    return {"id": dosage.id, "updated": True}


async def remove_dosage(db: AsyncSession, dosage_id: str) -> dict:
    """Hard-delete a single dosage entry."""
    result = await db.execute(select(Dosage).where(Dosage.id == dosage_id))
    dosage = result.scalar_one_or_none()
    if not dosage:
        return {"error": "Dosage not found"}
    await db.delete(dosage)
    await db.commit()
    return {"deleted": True, "id": dosage_id}


async def schedule_appointment(
    db: AsyncSession, patient_id: str, user_id: str, doctor_name: str, specialty: str | None,
    scheduled_for: datetime, notes: str | None,
) -> dict:
    """Insert a new Appointment row, marked as confirmed after HITL approval."""
    appt = Appointment(
        patient_id=patient_id, user_id=user_id, doctor_name=doctor_name, specialty=specialty,
        scheduled_for=scheduled_for, notes=notes, status="confirmed",
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    return {"id": appt.id, "doctor_name": appt.doctor_name, "scheduled_for": appt.scheduled_for.isoformat()}


async def order_pharmacy_refill(
    db: AsyncSession, patient_id: str, medicine_id: str, quantity: int = 30, partner: str = "Tata 1mg",
) -> dict:
    """Simulate pharmacy refill order dispatch after HITL approval."""
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.patient_id == patient_id))
    med = result.scalar_one_or_none()
    if not med:
        return {"error": "Medicine not found"}

    if med.supply_count is None:
        med.supply_count = quantity
    else:
        med.supply_count += quantity

    await db.commit()
    return {
        "status": "refill_ordered",
        "medicine_name": med.name,
        "new_supply_count": med.supply_count,
        "partner": partner,
        "message": f"Refill of {quantity} units of {med.name} ordered via {partner}.",
    }
