"""
API router for Patient Check-in touchpoints, voice/text replies, history, and public elderly-friendly view.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_patient_context, get_current_user
from app.db.models import CaregiverPatient, Patient, PatientCheckIn, User
from app.db.session import get_db
from app.services.checkin_service import process_checkin_reply, trigger_patient_checkin

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


class TriggerCheckinRequest(BaseModel):
    channel: str = "whatsapp_voice"  # whatsapp_voice | whatsapp_text | ivr_call | app


class ConfirmCheckinPublicRequest(BaseModel):
    share_token: str
    status: str = "taken"  # taken | missed
    notes: str | None = None


@router.post("/trigger/{patient_id}")
async def trigger_checkin(
    patient_id: str,
    req: TriggerCheckinRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an outbound check-in message to the patient (WhatsApp voice/text or IVR call)."""
    channel = req.channel if req else "whatsapp_voice"
    check_in = await trigger_patient_checkin(db, patient_id=patient_id, channel=channel)
    return {
        "id": check_in.id,
        "patient_id": patient_id,
        "channel": channel,
        "status": check_in.status,
        "scheduled_at": check_in.scheduled_at.isoformat(),
        "message": f"Daily check-in touchpoint dispatched via {channel}.",
    }


@router.post("/reply")
async def checkin_reply(
    checkin_id: str = Form(...),
    text_reply: str | None = Form(default=None),
    audio_file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Ingest a patient's check-in reply (text or voice note audio upload)."""
    audio_bytes = await audio_file.read() if audio_file else None
    audio_filename = audio_file.filename if audio_file else None

    result = await process_checkin_reply(
        db,
        checkin_id=checkin_id,
        raw_text=text_reply,
        audio_bytes=audio_bytes,
        audio_filename=audio_filename,
    )
    return result


@router.get("/history/{patient_id}")
async def get_checkin_history(
    patient_id: str,
    limit: int = 15,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent check-in log history for a patient."""
    stmt = (
        select(PatientCheckIn)
        .where(PatientCheckIn.patient_id == patient_id)
        .order_by(PatientCheckIn.scheduled_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    checkins = res.scalars().all()

    logs = []
    for c in checkins:
        logs.append({
            "id": c.id,
            "scheduled_at": c.scheduled_at.isoformat(),
            "responded_at": c.responded_at.isoformat() if c.responded_at else None,
            "channel": c.channel,
            "status": c.status,
            "transcript": c.transcript,
            "dose_details": c.dose_details,
        })
    return {"history": logs}


@router.get("/public/{share_token}")
async def get_public_checkin_info(
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public read endpoint for simplified tech-comfortable patient view."""
    stmt = select(CaregiverPatient).where(CaregiverPatient.share_token == share_token)
    res = await db.execute(stmt)
    link = res.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Invalid share token.")

    p_stmt = select(Patient).where(Patient.id == link.patient_id)
    p_res = await db.execute(p_stmt)
    patient = p_res.scalar_one_or_none()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found.")

    return {
        "patient_name": patient.name,
        "primary_language": patient.primary_language,
        "share_token": share_token,
    }


@router.post("/public/confirm")
async def confirm_public_checkin(
    req: ConfirmCheckinPublicRequest,
    db: AsyncSession = Depends(get_db),
):
    """One-tap public check-in confirmation for tech-comfortable elderly patients."""
    stmt = select(CaregiverPatient).where(CaregiverPatient.share_token == req.share_token)
    res = await db.execute(stmt)
    link = res.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Invalid share token.")

    # Find active check-in or create one
    c_stmt = (
        select(PatientCheckIn)
        .where(PatientCheckIn.patient_id == link.patient_id)
        .order_by(PatientCheckIn.scheduled_at.desc())
    )
    c_res = await db.execute(c_stmt)
    check_in = c_res.scalars().first()

    if not check_in or check_in.status != "no_response":
        check_in = await trigger_patient_checkin(db, patient_id=link.patient_id, channel="app")

    result = await process_checkin_reply(
        db,
        checkin_id=check_in.id,
        raw_text=f"Confirmed dose via one-tap web touchpoint. Notes: {req.notes or 'None'}",
    )
    return {"status": "ok", "message": "Thank you! Daily check-in logged successfully.", "details": result}
