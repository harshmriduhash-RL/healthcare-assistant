"""
Background automation and pattern watching scheduler for CarePilot AI.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.db.models import Appointment, Dosage, Medicine, Notification, Patient, User
from app.db.session import AsyncSessionLocal
from app.services.alert_agent import check_alert_escalations, run_longitudinal_pattern_analysis

logger = logging.getLogger("scheduler")

DOSAGE_CHECK_INTERVAL_MINUTES = 5
APPOINTMENT_CHECK_INTERVAL_MINUTES = 30
APPOINTMENT_REMINDER_WINDOW_HOURS = 24


async def _already_notified_recently(db, user_id: str, notification_type: str, related_id: str, within_minutes: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.notification_type == notification_type,
            Notification.related_id == related_id,
            Notification.created_at >= cutoff,
        )
    )
    return result.scalar_one_or_none() is not None


async def check_dosages_due() -> None:
    now = datetime.now(timezone.utc)
    current_hhmm = now.strftime("%H:%M")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Dosage, Medicine)
            .join(Medicine, Dosage.medicine_id == Medicine.id)
            .where(Dosage.is_active == True, Medicine.is_active == True)  # noqa: E712
        )
        rows = result.all()

        for dosage, medicine in rows:
            if not dosage.time_of_day:
                continue
            times = [t.strip() for t in dosage.time_of_day.split(",") if t.strip()]
            due = any(_within_window(current_hhmm, t, DOSAGE_CHECK_INTERVAL_MINUTES) for t in times)
            if not due:
                continue

            user_id = medicine.user_id
            if not user_id:
                continue
            if await _already_notified_recently(db, user_id, "dosage_due", dosage.id, within_minutes=60):
                continue

            db.add(Notification(
                user_id=user_id,
                patient_id=medicine.patient_id,
                notification_type="dosage_due",
                title=f"Time to take {medicine.name}",
                body=f"{dosage.amount} - {dosage.frequency}" + (f" ({dosage.consumption_instructions})" if dosage.consumption_instructions else ""),
                related_id=dosage.id,
                action_payload={"action": "mark_taken", "dosage_id": dosage.id, "medicine_id": medicine.id}
            ))
        await db.commit()


def _within_window(current_hhmm: str, target_hhmm: str, window_minutes: int) -> bool:
    try:
        cur = datetime.strptime(current_hhmm, "%H:%M")
        target = datetime.strptime(target_hhmm, "%H:%M")
    except ValueError:
        return False
    return abs((cur - target).total_seconds()) <= window_minutes * 60


async def run_pattern_watcher_job() -> None:
    """Scan all active patients for longitudinal pattern anomalies and handle alert escalations."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Patient.id).where(Patient.is_active == True))
        patient_ids = res.scalars().all()
        for pid in patient_ids:
            try:
                await run_longitudinal_pattern_analysis(db, pid)
            except Exception as e:
                logger.error(f"Error running pattern watcher for patient {pid}: {e}")

        try:
            await check_alert_escalations(db, escalation_window_minutes=15)
        except Exception as e:
            logger.error(f"Error checking alert escalations: {e}")


_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(check_dosages_due, "interval", minutes=DOSAGE_CHECK_INTERVAL_MINUTES, id="dosage_check")
    _scheduler.add_job(run_pattern_watcher_job, "interval", minutes=15, id="pattern_watcher_check")
    _scheduler.start()
    logger.info("CarePilot background scheduler started.")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
