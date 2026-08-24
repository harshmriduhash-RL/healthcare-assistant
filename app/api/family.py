"""
API router for Family Coordination: shared activity feed and family task management (§7.4).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import AgentAuditLog, CaregiverPatient, FamilyTask, MedicalRecord, PatientAlert, PatientCheckIn, User
from app.db.session import get_db

router = APIRouter(prefix="/api/family", tags=["family"])


class CreateTaskRequest(BaseModel):
    title: str
    description: str | None = None
    assigned_to_user_id: str | None = None
    due_date: str | None = None


class UpdateTaskStatusRequest(BaseModel):
    status: str  # pending | completed


@router.get("/{patient_id}/feed")
async def get_family_activity_feed(
    patient_id: str,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unified shared activity feed visible to all caregivers linked to the patient."""
    feed = []

    # 1. Recent Check-ins
    ci_stmt = (
        select(PatientCheckIn)
        .where(PatientCheckIn.patient_id == patient_id)
        .order_by(PatientCheckIn.scheduled_at.desc())
        .limit(10)
    )
    ci_res = await db.execute(ci_stmt)
    for c in ci_res.scalars().all():
        feed.append({
            "type": "checkin",
            "title": f"Daily Check-in ({c.status.upper()})",
            "description": c.transcript or f"Channel: {c.channel}",
            "timestamp": c.scheduled_at.isoformat(),
            "badge": "success" if c.status == "taken" else ("warning" if c.status == "unclear" else "danger"),
        })

    # 2. Alerts
    a_stmt = (
        select(PatientAlert)
        .where(PatientAlert.patient_id == patient_id)
        .order_by(PatientAlert.created_at.desc())
        .limit(10)
    )
    a_res = await db.execute(a_stmt)
    for a in a_res.scalars().all():
        feed.append({
            "type": "alert",
            "title": f"[{a.severity.upper()}] {a.title}",
            "description": a.body,
            "timestamp": a.created_at.isoformat(),
            "badge": "danger" if a.severity == "critical" else "warning",
        })

    # 3. Document Uploads
    r_stmt = (
        select(MedicalRecord)
        .where(MedicalRecord.patient_id == patient_id)
        .order_by(MedicalRecord.uploaded_at.desc())
        .limit(10)
    )
    r_res = await db.execute(r_stmt)
    for r in r_res.scalars().all():
        feed.append({
            "type": "record",
            "title": f"Uploaded Document: {r.filename}",
            "description": r.extracted_summary or "Medical record added.",
            "timestamp": r.uploaded_at.isoformat(),
            "badge": "info",
        })

    # Sort feed by timestamp descending
    feed.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"feed": feed[:limit]}


@router.get("/{patient_id}/tasks")
async def list_family_tasks(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List family care tasks for a patient."""
    stmt = (
        select(FamilyTask)
        .where(FamilyTask.patient_id == patient_id)
        .order_by(FamilyTask.created_at.desc())
    )
    res = await db.execute(stmt)
    tasks = res.scalars().all()

    output = []
    for t in tasks:
        output.append({
            "id": t.id,
            "patient_id": t.patient_id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "created_at": t.created_at.isoformat(),
        })
    return {"tasks": output}


@router.post("/{patient_id}/tasks")
async def create_family_task(
    patient_id: str,
    req: CreateTaskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new family care task."""
    due_dt = None
    if req.due_date:
        try:
            due_dt = datetime.fromisoformat(req.due_date)
        except ValueError:
            pass

    task = FamilyTask(
        patient_id=patient_id,
        title=req.title,
        description=req.description,
        assigned_to_user_id=req.assigned_to_user_id or user.id,
        created_by_user_id=user.id,
        due_date=due_dt,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    return {"id": task.id, "title": task.title, "status": task.status}


@router.put("/tasks/{task_id}/status")
async def update_task_status(
    task_id: str,
    req: UpdateTaskStatusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update task completion status."""
    stmt = select(FamilyTask).where(FamilyTask.id == task_id)
    res = await db.execute(stmt)
    task = res.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    task.status = req.status
    await db.commit()
    return {"status": "ok", "id": task.id, "task_status": task.status}
