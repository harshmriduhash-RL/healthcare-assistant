"""
API router for Wearables, Vitals Sync, Fall Detection, and One-Tap Emergency Mode (§7.6).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import CaregiverPatient, Medicine, Notification, Patient, PatientAlert, User, VitalsLog
from app.db.session import get_db

router = APIRouter(prefix="/api/emergency", tags=["emergency"])


class LogVitalRequest(BaseModel):
    patient_id: str
    vital_type: str  # bp_sys | bp_dia | hr | glucose | hba1c | oxygen | weight
    value: float
    unit: str | None = None
    source: str = "wearable"  # wearable | manual | lab_report
    notes: str | None = None


@router.post("/vitals/sync")
async def sync_vital_reading(
    req: LogVitalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a vital reading from a wearable device or manual entry."""
    unit_map = {
        "bp_sys": "mmHg", "bp_dia": "mmHg", "hr": "bpm",
        "glucose": "mg/dL", "hba1c": "%", "oxygen": "%", "weight": "kg",
    }

    vital = VitalsLog(
        patient_id=req.patient_id,
        vital_type=req.vital_type,
        value=req.value,
        unit=req.unit or unit_map.get(req.vital_type, ""),
        source=req.source,
        notes=req.notes,
        logged_at=datetime.now(timezone.utc),
    )
    db.add(vital)
    await db.commit()
    await db.refresh(vital)

    return {"status": "ok", "id": vital.id, "vital_type": vital.vital_type, "value": vital.value}


@router.get("/vitals/{patient_id}")
async def get_patient_vitals_history(
    patient_id: str,
    limit: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get time-series vitals history for charting."""
    stmt = (
        select(VitalsLog)
        .where(VitalsLog.patient_id == patient_id)
        .order_by(VitalsLog.logged_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    vitals = res.scalars().all()

    logs = []
    for v in vitals:
        logs.append({
            "id": v.id,
            "vital_type": v.vital_type,
            "value": v.value,
            "unit": v.unit,
            "source": v.source,
            "logged_at": v.logged_at.isoformat(),
        })
    return {"vitals": logs}


@router.post("/trigger/{patient_id}")
async def trigger_emergency_mode(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One-Tap Emergency Mode: notify all caregivers, generate critical alert, and surface doctor summary."""
    p_res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = p_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    # Create critical alert
    alert = PatientAlert(
        patient_id=patient_id,
        severity="critical",
        title=f"EMERGENCY SOS: Activated for {patient.name}",
        body=f"One-Tap Emergency mode triggered. Contact emergency contact: {patient.emergency_contact_phone or patient.phone_number or 'On file'}.",
        pattern_type="emergency_mode",
    )
    db.add(alert)
    await db.commit()

    # Notify all linked caregivers
    c_stmt = select(CaregiverPatient).where(CaregiverPatient.patient_id == patient_id)
    c_res = await db.execute(c_stmt)
    links = c_res.scalars().all()

    for link in links:
        notif = Notification(
            user_id=link.user_id,
            patient_id=patient_id,
            notification_type="alert_escalation",
            title=f"🚨 EMERGENCY ALERT: {patient.name}",
            body=f"Emergency mode activated. Immediate family response requested.",
            related_id=alert.id,
        )
        db.add(notif)

    await db.commit()

    # Query active medicines for emergency view
    m_stmt = select(Medicine).where(Medicine.patient_id == patient_id, Medicine.is_active == True)
    m_res = await db.execute(m_stmt)
    medicines = m_res.scalars().all()

    return {
        "status": "emergency_activated",
        "alert_id": alert.id,
        "patient": {
            "name": patient.name,
            "age": patient.age_or_dob,
            "emergency_phone": patient.emergency_contact_phone or patient.phone_number,
            "abdm_id": patient.abdm_id,
        },
        "active_medicines": [{"name": m.name, "strength": m.strength} for m in medicines],
        "message": "Emergency notifications dispatched to all family caregivers.",
    }


@router.post("/sim-fall/{patient_id}")
async def simulate_fall_detection(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Simulate fall detection event from smartwatch wearable."""
    p_res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = p_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    alert = PatientAlert(
        patient_id=patient_id,
        severity="critical",
        title=f"Fall Detected: Smartwatch alert for {patient.name}",
        body=f"Impact detected on wearable device at {datetime.now(timezone.utc).strftime('%H:%M UTC')}. Patient may require immediate check-in.",
        pattern_type="fall_detection",
    )
    db.add(alert)
    await db.commit()

    return {"status": "fall_alert_triggered", "alert_id": alert.id, "title": alert.title}
