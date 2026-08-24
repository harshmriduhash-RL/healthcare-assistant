"""
API router for Patient Intelligence Alerts and Escalations.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import CaregiverPatient, PatientAlert, User
from app.db.session import get_db
from app.services.alert_agent import check_alert_escalations, run_longitudinal_pattern_analysis

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/{patient_id}")
async def list_alerts(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List alerts for a patient."""
    stmt = (
        select(PatientAlert)
        .where(PatientAlert.patient_id == patient_id)
        .order_by(PatientAlert.created_at.desc())
    )
    res = await db.execute(stmt)
    alerts = res.scalars().all()

    output = []
    for a in alerts:
        output.append({
            "id": a.id,
            "patient_id": a.patient_id,
            "severity": a.severity,
            "title": a.title,
            "body": a.body,
            "pattern_type": a.pattern_type,
            "is_acknowledged": a.is_acknowledged,
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
            "is_escalated": a.is_escalated,
            "escalated_at": a.escalated_at.isoformat() if a.escalated_at else None,
            "created_at": a.created_at.isoformat(),
        })
    return {"alerts": output}


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Caregiver acknowledges an alert."""
    stmt = select(PatientAlert).where(PatientAlert.id == alert_id)
    res = await db.execute(stmt)
    alert = res.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")

    alert.is_acknowledged = True
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by_user_id = user.id
    await db.commit()

    return {"status": "ok", "message": "Alert acknowledged."}


@router.post("/run-analysis/{patient_id}")
async def trigger_longitudinal_analysis(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger pattern watching analysis manually (for demo/testing)."""
    alerts = await run_longitudinal_pattern_analysis(db, patient_id)
    return {
        "status": "completed",
        "new_alerts_count": len(alerts),
        "alerts": [{"id": a.id, "title": a.title, "severity": a.severity} for a in alerts],
    }


@router.post("/test-escalate/{patient_id}")
async def force_test_escalation(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Force escalation check on unacknowledged alerts for live demo."""
    escalated = await check_alert_escalations(db, escalation_window_minutes=0)
    return {
        "status": "completed",
        "escalated_count": len(escalated),
        "escalated_alerts": [{"id": a.id, "title": a.title} for a in escalated],
    }
