"""
API router for India-Specific Value-Add features: Generic med lookup, Spend tracking, ABHA ID verification (§7.5).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services.india_health import (
    calculate_patient_spend,
    find_generic_substitute,
    verify_abdm_abha,
)

router = APIRouter(prefix="/api/india", tags=["india"])


class VerifyAbhaRequest(BaseModel):
    abha_id: str


@router.get("/generic-substitute/{medicine_name}")
async def get_generic_substitute(
    medicine_name: str,
    user: User = Depends(get_current_user),
):
    """Lookup generic substitute and price comparison in ₹ INR."""
    return find_generic_substitute(medicine_name)


@router.get("/spend/{patient_id}")
async def get_patient_spend(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get total monthly medicine spend breakdown and generic savings potential for a patient."""
    return await calculate_patient_spend(db, patient_id)


@router.post("/verify-abha")
async def verify_abha(
    req: VerifyAbhaRequest,
    user: User = Depends(get_current_user),
):
    """Simulate ABHA Health ID verification."""
    return verify_abdm_abha(req.abha_id)
