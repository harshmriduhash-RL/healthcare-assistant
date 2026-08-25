"""
Notification routes: list a user's reminders and mark them read.

The notifications themselves are created entirely by the background
scheduler (app/core/scheduler.py), not by anything here -- this file is
purely read/update, no creation logic. See the module docstring in
scheduler.py for why the scheduler is kept separate from the agent/HITL
system.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_patient_context, get_current_user
from app.db.models import Notification, User, Medicine, MedicationLog, Patient
from app.db.session import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/")
async def list_notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List this user's most recent 50 notifications (read and unread),
    newest first. The dashboard uses the unread ones to show a badge
    count on the reminders bell.
    """
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    notifications = result.scalars().all()
    return [
        {
            "id": n.id, "type": n.notification_type, "title": n.title, "body": n.body,
            "is_read": n.is_read, "created_at": n.created_at.isoformat(),
            "action_payload": n.action_payload,
        }
        for n in notifications
    ]


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Mark one specific notification as read."""
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Mark every unread notification for this user as read in one query
    -- called when the user opens the reminders panel on the dashboard.
    """
    await db.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.is_read == False).values(is_read=True)  # noqa: E712
    )
    await db.commit()
    return {"ok": True}


@router.post("/{notification_id}/action")
async def take_action(notification_id: str, patient: Patient = Depends(get_current_patient_context), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Handle one-tap actions from notifications (e.g., mark as taken, request refill)."""
    # 1. Fetch notification
    result = await db.execute(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    notification = result.scalar_one_or_none()
    
    if not notification or not notification.action_payload:
        raise HTTPException(status_code=400, detail="Invalid action or notification not found")

    action = notification.action_payload.get("action")
    medicine_id = notification.action_payload.get("medicine_id")

    if not action or not medicine_id:
        raise HTTPException(status_code=400, detail="Malformed action payload")

    # 2. Fetch the associated medicine
    med_result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.patient_id == patient.id))
    medicine = med_result.scalar_one_or_none()

    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")

    if action == "mark_taken":
        dosage_id = notification.action_payload.get("dosage_id")
        if not dosage_id:
            raise HTTPException(status_code=400, detail="Missing dosage_id for mark_taken")
            
        # Log the dose
        db.add(MedicationLog(
            patient_id=patient.id,
            user_id=user.id,
            medicine_id=medicine.id,
            dosage_id=dosage_id,
            status="taken"
        ))
        
        # Decrement supply
        if medicine.supply_count is not None and medicine.supply_count > 0:
            medicine.supply_count -= 1
            
        # Increment streak
        medicine.current_streak += 1
        if medicine.current_streak > medicine.longest_streak:
            medicine.longest_streak = medicine.current_streak

    elif action == "request_refill":
        # Create a persistent draft message/reminder for the user
        db.add(Notification(
            user_id=user.id,
            notification_type="refill_reminder",
            title=f"Call pharmacy for {medicine.name}",
            body=f"Drafted request: Please refill my prescription for {medicine.name}. (This is a reminder to call them)",
            related_id=medicine.id
        ))
    else:
        raise HTTPException(status_code=400, detail="Unknown action")

    # Mark notification as read
    notification.is_read = True
    await db.commit()

    return {"ok": True, "message": f"Action '{action}' completed successfully"}

