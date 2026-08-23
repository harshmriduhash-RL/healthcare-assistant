"""
Background automation, deliberately kept outside the agent graph.

This scheduler only ever creates Notification rows -- it never touches
medicines, dosages, or appointments directly, and it never calls the
LangGraph agents. If a reminder should ever turn into an action (e.g.
"auto-reschedule this missed appointment"), that has to be proposed by
an agent and pass through the same human_approval_node as everything
else -- the scheduler doesn't get a side door around HITL.

Started once from the FastAPI lifespan in app/main.py, and stopped
cleanly on app shutdown.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.db.models import Appointment, Dosage, Medicine, Notification, User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger("scheduler")

# How often each background job runs, and how far ahead it looks.
# Tuned for demo-friendliness (short intervals so reminders show up
# quickly when presenting) rather than production efficiency.
DOSAGE_CHECK_INTERVAL_MINUTES = 5
APPOINTMENT_CHECK_INTERVAL_MINUTES = 30
APPOINTMENT_REMINDER_WINDOW_HOURS = 24


async def _already_notified_recently(db, user_id: str, notification_type: str, related_id: str, within_minutes: int) -> bool:
    """Dedup helper: has this exact reminder (same type + same underlying
    dosage/appointment id) already fired for this user within the given
    window? Without this, a job that runs every 5 minutes would spam a
    fresh notification every single run while the condition stays true.
    """
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
    """Job: scan all active dosages and notify users whose dose time has
    just arrived.

    Simple time-of-day match against `dosages.time_of_day` (a
    comma-separated string of HH:MM values, e.g. "08:00,20:00"). This is
    intentionally simple for the prototype: it compares the current UTC
    time to each active dosage's scheduled time-of-day strings within the
    current check window, rather than modeling full recurrence rules,
    per-user timezones, or "already taken today" tracking.
    """
    now = datetime.now(timezone.utc)
    current_hhmm = now.strftime("%H:%M")

    async with AsyncSessionLocal() as db:
        # Join dosages -> medicines so we can filter to only medicines/
        # dosages that are still active (not soft-deleted/discontinued),
        # and so we have medicine.name + medicine.user_id available for
        # building the notification without a second query per row.
        result = await db.execute(
            select(Dosage, Medicine)
            .join(Medicine, Dosage.medicine_id == Medicine.id)
            .where(Dosage.is_active == True, Medicine.is_active == True)  # noqa: E712
        )
        rows = result.all()

        for dosage, medicine in rows:
            if not dosage.time_of_day:
                continue  # no schedule set for this dosage -- nothing to check
            times = [t.strip() for t in dosage.time_of_day.split(",") if t.strip()]
            # "due" means the current time falls within DOSAGE_CHECK_INTERVAL_MINUTES
            # of any one of this dosage's scheduled times -- this is what lets a
            # job that runs every 5 minutes still reliably catch a dose scheduled
            # for e.g. exactly 08:00 even if the job fires at 08:02.
            due = any(_within_window(current_hhmm, t, DOSAGE_CHECK_INTERVAL_MINUTES) for t in times)
            if not due:
                continue

            # Don't re-notify for the same dosage within the same hour --
            # otherwise every 5-minute run inside the matching window would
            # fire a duplicate notification.
            if await _already_notified_recently(db, medicine.user_id, "dosage_due", dosage.id, within_minutes=60):
                continue

            db.add(Notification(
                user_id=medicine.user_id,
                notification_type="dosage_due",
                title=f"Time to take {medicine.name}",
                body=f"{dosage.amount} - {dosage.frequency}" + (f" ({dosage.consumption_instructions})" if dosage.consumption_instructions else ""),
                related_id=dosage.id,
                action_payload={"action": "mark_taken", "dosage_id": dosage.id, "medicine_id": medicine.id}
            ))
        await db.commit()


def _within_window(current_hhmm: str, target_hhmm: str, window_minutes: int) -> bool:
    """True if `current_hhmm` is within `window_minutes` of `target_hhmm`,
    both given as "HH:MM" strings. Used only to compare clock times
    (not full dates), so we parse both onto the same arbitrary date
    (datetime.strptime defaults to 1900-01-01) purely so we can subtract
    them and get a timedelta.
    """
    try:
        cur = datetime.strptime(current_hhmm, "%H:%M")
        target = datetime.strptime(target_hhmm, "%H:%M")
    except ValueError:
        # A malformed time_of_day string (bad user input) -- treat as "not due"
        # rather than crashing the whole scheduled job for every other user.
        return False
    return abs((cur - target).total_seconds()) <= window_minutes * 60


async def check_upcoming_appointments() -> None:
    """Job: find confirmed appointments happening in the next
    APPOINTMENT_REMINDER_WINDOW_HOURS (24h) and notify the user.
    """
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=APPOINTMENT_REMINDER_WINDOW_HOURS)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Appointment).where(
                Appointment.status == "confirmed",
                Appointment.scheduled_for >= now,
                Appointment.scheduled_for <= window_end,
            )
        )
        appointments = result.scalars().all()

        for appt in appointments:
            # Dedup window equals the full reminder window (24h) -- a given
            # appointment should only trigger one "upcoming" notification
            # per day it's within range, not one every 30-minute check.
            if await _already_notified_recently(db, appt.user_id, "appointment_upcoming", appt.id, within_minutes=60 * APPOINTMENT_REMINDER_WINDOW_HOURS):
                continue

            db.add(Notification(
                user_id=appt.user_id,
                notification_type="appointment_upcoming",
                title=f"Upcoming appointment with {appt.doctor_name}",
                body=f"{appt.scheduled_for.strftime('%a %b %d, %I:%M %p')}" + (f" - {appt.specialty}" if appt.specialty else ""),
                related_id=appt.id,
            ))
        await db.commit()

async def check_pre_appointment_prep() -> None:
    """Job: find confirmed appointments happening in the next 48h and prompt for prep."""
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=24)
    window_end = now + timedelta(hours=48)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Appointment).where(
                Appointment.status == "confirmed",
                Appointment.scheduled_for >= window_start,
                Appointment.scheduled_for <= window_end,
            )
        )
        appointments = result.scalars().all()

        for appt in appointments:
            if await _already_notified_recently(db, appt.user_id, "pre_appointment_prep", appt.id, within_minutes=24 * 60):
                continue

            db.add(Notification(
                user_id=appt.user_id,
                notification_type="pre_appointment_prep",
                title=f"Prepare for your visit with {appt.doctor_name}",
                body="Any recent symptoms to note? Make sure to upload your latest lab reports before the visit.",
                related_id=appt.id,
            ))
        await db.commit()


async def check_low_supply() -> None:
    """Job: scan active medicines and notify if supply_count drops below refill_threshold."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Medicine).where(Medicine.is_active == True, Medicine.supply_count != None, Medicine.refill_threshold != None) # noqa: E711
        )
        medicines = result.scalars().all()
        for medicine in medicines:
            if medicine.supply_count <= medicine.refill_threshold:
                if await _already_notified_recently(db, medicine.user_id, "low_supply", medicine.id, within_minutes=24 * 60):
                    continue
                db.add(Notification(
                    user_id=medicine.user_id,
                    notification_type="low_supply",
                    title=f"Low Supply: {medicine.name}",
                    body=f"You have {medicine.supply_count} doses left. Time to refill!",
                    related_id=medicine.id,
                    action_payload={"action": "request_refill", "medicine_id": medicine.id}
                ))
        await db.commit()


async def generate_daily_digest() -> None:
    """Job: scan active users and generate a Daily Health Digest in the morning."""
    now = datetime.now(timezone.utc)
    # Only run between 7AM and 9AM UTC (or appropriate local time, simplified for prototype)
    if not (7 <= now.hour <= 9):
        return

    async with AsyncSessionLocal() as db:
        # Get all users who have active medicines or appointments today
        result = await db.execute(select(User.id))
        user_ids = result.scalars().all()

        for uid in user_ids:
            if await _already_notified_recently(db, uid, "daily_digest", "digest", within_minutes=12 * 60):
                continue
            
            # Simple summary for prototype
            # In a real app, query today's doses and appointments to build the string
            db.add(Notification(
                user_id=uid,
                notification_type="daily_digest",
                title="Daily Health Digest",
                body="Check your dashboard for today's doses, appointments, and adherence streaks.",
                related_id="digest"
            ))
        await db.commit()


# Module-level singleton so start_scheduler()/stop_scheduler() can be called
# from FastAPI's lifespan without needing to pass a scheduler instance around.
_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    """Create (if needed) and start the background job scheduler.

    Idempotent: calling this twice just returns the already-running
    scheduler instead of starting a second one, which matters because
    FastAPI's --reload dev mode can sometimes trigger startup twice.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()
    # "interval" trigger = run repeatedly forever, every N minutes, starting
    # roughly N minutes after the scheduler starts. `id` gives each job a
    # stable name (useful for logs/debugging, and required if we ever want
    # to look the job up later to pause/modify it).
    _scheduler.add_job(check_dosages_due, "interval", minutes=DOSAGE_CHECK_INTERVAL_MINUTES, id="dosage_check")
    _scheduler.add_job(check_upcoming_appointments, "interval", minutes=APPOINTMENT_CHECK_INTERVAL_MINUTES, id="appointment_check")
    _scheduler.add_job(check_pre_appointment_prep, "interval", minutes=60, id="pre_appointment_prep")
    _scheduler.add_job(check_low_supply, "interval", minutes=60, id="low_supply_check")
    _scheduler.add_job(generate_daily_digest, "interval", minutes=60, id="daily_digest_check")
    _scheduler.start()
    logger.info("Scheduler started: dosage checks every %sm, appointment checks every %sm",
                DOSAGE_CHECK_INTERVAL_MINUTES, APPOINTMENT_CHECK_INTERVAL_MINUTES)
    return _scheduler


def stop_scheduler() -> None:
    """Stop the scheduler cleanly. Called from FastAPI's lifespan shutdown
    so background jobs don't keep firing after the app has stopped serving
    requests (and so `uvicorn --reload` doesn't accumulate duplicate
    schedulers across reloads).
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)  # don't block shutdown waiting for an in-flight job
        _scheduler = None
