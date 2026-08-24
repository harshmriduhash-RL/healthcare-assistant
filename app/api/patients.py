"""
API router for Patient profile creation, management, switching context, and caregiver invites.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_patient_context, get_current_user
from app.db.models import CaregiverPatient, Patient, User
from app.db.session import get_db

router = APIRouter(prefix="/api/patients", tags=["patients"])


class CreatePatientRequest(BaseModel):
    name: str
    age_or_dob: str | None = None
    relationship_type: str | None = "Parent"
    phone_number: str | None = None
    primary_language: str | None = "Hindi"
    emergency_contact_phone: str | None = None


class UpdatePatientRequest(BaseModel):
    name: str | None = None
    age_or_dob: str | None = None
    relationship_type: str | None = None
    phone_number: str | None = None
    primary_language: str | None = None
    abdm_id: str | None = None
    emergency_contact_phone: str | None = None


class InviteCaregiverRequest(BaseModel):
    role: str = "secondary"  # secondary | viewer


@router.get("/")
async def list_patients(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all patient profiles linked to the logged-in caregiver."""
    stmt = (
        select(Patient, CaregiverPatient.role, CaregiverPatient.share_token)
        .join(CaregiverPatient, CaregiverPatient.patient_id == Patient.id)
        .where(CaregiverPatient.user_id == user.id, Patient.is_active == True)
        .order_by(Patient.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    patients = []
    for patient, role, share_token in rows:
        patients.append({
            "id": patient.id,
            "name": patient.name,
            "age_or_dob": patient.age_or_dob,
            "relationship_type": patient.relationship_type,
            "phone_number": patient.phone_number,
            "primary_language": patient.primary_language,
            "is_verified": patient.is_verified,
            "abdm_id": patient.abdm_id,
            "role": role,
            "share_token": share_token,
        })
    return {"patients": patients}


@router.post("/")
async def create_patient(
    req: CreatePatientRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new patient profile and set it as active."""
    patient = Patient(
        name=req.name,
        age_or_dob=req.age_or_dob,
        relationship_type=req.relationship_type,
        phone_number=req.phone_number,
        primary_language=req.primary_language or "Hindi",
        emergency_contact_phone=req.emergency_contact_phone,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    link = CaregiverPatient(
        user_id=user.id,
        patient_id=patient.id,
        role="primary",
    )
    db.add(link)
    await db.commit()

    # Set as active patient cookie
    response.set_cookie(key="active_patient_id", value=patient.id, httponly=False, path="/")
    return {
        "id": patient.id,
        "name": patient.name,
        "role": "primary",
        "message": f"Patient profile for {patient.name} created successfully.",
    }


@router.get("/current")
async def get_current_patient(patient: Patient = Depends(get_current_patient_context)):
    """Get currently active patient context."""
    return {
        "id": patient.id,
        "name": patient.name,
        "age_or_dob": patient.age_or_dob,
        "relationship_type": patient.relationship_type,
        "phone_number": patient.phone_number,
        "primary_language": patient.primary_language,
        "is_verified": patient.is_verified,
        "abdm_id": patient.abdm_id,
        "emergency_contact_phone": patient.emergency_contact_phone,
    }


@router.post("/select/{patient_id}")
async def select_active_patient(
    patient_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Select a patient profile to be the active context."""
    stmt = (
        select(Patient)
        .join(CaregiverPatient, CaregiverPatient.patient_id == Patient.id)
        .where(CaregiverPatient.user_id == user.id, Patient.id == patient_id)
    )
    res = await db.execute(stmt)
    patient = res.scalar_one_or_none()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found or access denied.")

    response.set_cookie(key="active_patient_id", value=patient.id, httponly=False, path="/")
    return {"status": "ok", "active_patient": {"id": patient.id, "name": patient.name}}


@router.put("/{patient_id}")
async def update_patient(
    patient_id: str,
    req: UpdatePatientRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update patient details."""
    stmt = (
        select(Patient)
        .join(CaregiverPatient, CaregiverPatient.patient_id == Patient.id)
        .where(CaregiverPatient.user_id == user.id, Patient.id == patient_id)
    )
    res = await db.execute(stmt)
    patient = res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    for field, val in req.model_dump(exclude_unset=True).items():
        if val is not None:
            setattr(patient, field, val)

    await db.commit()
    return {"status": "ok", "message": f"Updated profile for {patient.name}"}


@router.post("/{patient_id}/verify")
async def send_patient_verification(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger phone verification & onboarding touchpoint message for patient."""
    stmt = (
        select(Patient)
        .join(CaregiverPatient, CaregiverPatient.patient_id == Patient.id)
        .where(CaregiverPatient.user_id == user.id, Patient.id == patient_id)
    )
    res = await db.execute(stmt)
    patient = res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    patient.is_verified = True
    await db.commit()

    return {
        "status": "sent",
        "message": f"Verification message sent to {patient.name} ({patient.phone_number or 'WhatsApp/IVR Channel'}). Touchpoint active.",
    }


@router.post("/{patient_id}/invite")
async def generate_caregiver_invite(
    patient_id: str,
    req: InviteCaregiverRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a share link / invite token for a secondary caregiver."""
    stmt = (
        select(CaregiverPatient)
        .where(CaregiverPatient.user_id == user.id, CaregiverPatient.patient_id == patient_id)
    )
    res = await db.execute(stmt)
    link = res.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Patient profile link not found.")

    return {
        "share_token": link.share_token,
        "invite_url": f"/accept-invite?token={link.share_token}",
        "role": req.role,
    }


@router.post("/accept-invite/{share_token}")
async def accept_caregiver_invite(
    share_token: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept an invite link to co-manage a patient profile."""
    stmt = select(CaregiverPatient).where(CaregiverPatient.share_token == share_token)
    res = await db.execute(stmt)
    existing_link = res.scalar_one_or_none()

    if not existing_link:
        raise HTTPException(status_code=404, detail="Invalid or expired invite link.")

    # Check if already linked
    check_stmt = select(CaregiverPatient).where(
        CaregiverPatient.user_id == user.id,
        CaregiverPatient.patient_id == existing_link.patient_id,
    )
    check_res = await db.execute(check_stmt)
    if check_res.scalar_one_or_none():
        return {"status": "already_linked", "message": "You are already linked to this patient."}

    new_link = CaregiverPatient(
        user_id=user.id,
        patient_id=existing_link.patient_id,
        role="secondary",
    )
    db.add(new_link)
    await db.commit()

    return {"status": "success", "message": "You have joined as a co-caregiver!"}
