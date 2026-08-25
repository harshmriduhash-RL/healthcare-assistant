"""
FastAPI dependencies for CarePilot AI:
1. get_current_user: Resolves Caregiver account from JWT cookie.
2. get_current_patient_context: Resolves active Patient profile for the Caregiver.
"""

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import CaregiverPatient, Patient, User
from app.db.session import get_db


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = decode_access_token(access_token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_patient_context(
    request: Request,
    user: User = Depends(get_current_user),
    active_patient_id: str | None = Cookie(default=None),
    x_patient_id: str | None = Header(default=None, alias="X-Patient-ID"),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    """Resolves the currently selected Patient for the logged-in Caregiver.

    Priority:
    1. X-Patient-ID header
    2. active_patient_id cookie
    3. First linked patient for this caregiver
    4. Auto-creates a default patient profile if none exists yet.
    """
    target_patient_id = x_patient_id or active_patient_id

    if target_patient_id:
        stmt = (
            select(Patient)
            .join(CaregiverPatient, CaregiverPatient.patient_id == Patient.id)
            .where(CaregiverPatient.user_id == user.id, Patient.id == target_patient_id, Patient.is_active == True)
        )
        result = await db.execute(stmt)
        patient = result.scalars().first()
        if patient:
            return patient

    # Fallback to caregiver's first linked patient
    stmt = (
        select(Patient)
        .join(CaregiverPatient, CaregiverPatient.patient_id == Patient.id)
        .where(CaregiverPatient.user_id == user.id, Patient.is_active == True)
        .order_by(CaregiverPatient.created_at.asc())
    )
    result = await db.execute(stmt)
    patient = result.scalars().first()

    if not patient:
        # Create a default patient profile for new caregivers
        patient = Patient(
            name="Ram Sharma",
            age_or_dob="68",
            relationship_type="Father",
            phone_number="+919876543210",
            primary_language="Hindi",
            is_verified=True,
            abdm_id="91-1234-5678-9012",
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

    return patient
