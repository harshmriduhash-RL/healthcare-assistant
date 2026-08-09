"""
Notification routes: list a user's reminders and mark them read.

The notifications themselves are created entirely by the background
scheduler (app/core/scheduler.py), not by anything here -- this file is
purely read/update, no creation logic. See the module docstring in
scheduler.py for why the scheduler is kept separate from the agent/HITL
system.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import Notification, User
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
