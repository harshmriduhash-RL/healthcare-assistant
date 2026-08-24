"""
Longitudinal Pattern-Watching Intelligence Agent for CarePilot AI (§7.2).

Performs pattern analysis across multi-day check-in histories, vitals trends,
drug-drug interactions, polypharmacy, and correlation between adherence dips and vitals.
Manages automatic escalation to secondary caregivers.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CaregiverPatient,
    Medicine,
    Notification,
    Patient,
    PatientAlert,
    PatientCheckIn,
    VitalsLog,
)

logger = logging.getLogger("alert_agent")

# Known high-risk drug interaction pairs (RxNav / clinical database dataset sample)
DRUG_INTERACTION_DATABASE = [
    {"pair": {"warfarin", "aspirin"}, "severity": "critical", "description": "Increased risk of major bleeding."},
    {"pair": {"lisinopril", "spironolactone"}, "severity": "warning", "description": "Risk of severe hyperkalemia (high blood potassium)."},
    {"pair": {"metformin", "furosemide"}, "severity": "warning", "description": "May alter metformin blood levels and glycemic control."},
    {"pair": {"amlodipine", "simvastatin"}, "severity": "warning", "description": "Increased risk of myopathy/rhabdomyolysis."},
    {"pair": {"digoxin", "amiodarone"}, "severity": "critical", "description": "Increased digoxin toxicity risk."},
]


async def run_longitudinal_pattern_analysis(db: AsyncSession, patient_id: str) -> list[PatientAlert]:
    """Run longitudinal pattern checks for a patient and return newly generated alerts."""
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    generated_alerts = []

    # Query patient details
    p_res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = p_res.scalar_one_or_none()
    if not patient:
        return []

    # 1. Missed/Unclear Check-ins Pattern (3+ in 7 days)
    ci_stmt = select(PatientCheckIn).where(
        PatientCheckIn.patient_id == patient_id,
        PatientCheckIn.scheduled_at >= seven_days_ago,
    )
    ci_res = await db.execute(ci_stmt)
    checkins = ci_res.scalars().all()

    missed_count = sum(1 for c in checkins if c.status in ("missed", "unclear"))
    if missed_count >= 3:
        # Check if already alerted recently
        alert_exists = await _recent_alert_exists(db, patient_id, "missed_checkins", hours=24)
        if not alert_exists:
            alert = PatientAlert(
                patient_id=patient_id,
                severity="warning",
                title=f"{patient.name} has 3+ missed/unclear check-ins this week",
                body=f"Pattern detected: {patient.name} missed or reported unclear responses on {missed_count} check-ins in the last 7 days. Consider checking in by phone.",
                pattern_type="missed_checkins",
            )
            db.add(alert)
            generated_alerts.append(alert)

    # 2. Check-in Gap (2+ consecutive no_response entries)
    recent_checkins = sorted(checkins, key=lambda x: x.scheduled_at, reverse=True)
    if len(recent_checkins) >= 2 and all(c.status == "no_response" for c in recent_checkins[:2]):
        alert_exists = await _recent_alert_exists(db, patient_id, "checkin_gap", hours=24)
        if not alert_exists:
            alert = PatientAlert(
                patient_id=patient_id,
                severity="warning",
                title=f"Check-in gap: {patient.name} hasn't responded for 2 consecutive days",
                body=f"{patient.name} has not responded to the daily touchpoint for 2 days in a row.",
                pattern_type="checkin_gap",
            )
            db.add(alert)
            generated_alerts.append(alert)

    # 3. Vitals Trend Anomaly (e.g. BP High > 140 for 2+ entries)
    v_stmt = select(VitalsLog).where(
        VitalsLog.patient_id == patient_id,
        VitalsLog.vital_type == "bp_sys",
        VitalsLog.logged_at >= seven_days_ago,
    ).order_by(VitalsLog.logged_at.desc())
    v_res = await db.execute(v_stmt)
    bp_logs = v_res.scalars().all()

    if len(bp_logs) >= 2 and bp_logs[0].value >= 140 and bp_logs[1].value >= 140:
        alert_exists = await _recent_alert_exists(db, patient_id, "vitals_trend", hours=24)
        if not alert_exists:
            body_text = f"Systolic BP recorded at {int(bp_logs[0].value)} mmHg today and {int(bp_logs[1].value)} mmHg previously."
            if missed_count > 0:
                body_text += f" Note: This correlates with {missed_count} missed medicine check-ins during the same window."
            alert = PatientAlert(
                patient_id=patient_id,
                severity="warning",
                title=f"Vitals trend: Elevated blood pressure detected for {patient.name}",
                body=body_text,
                pattern_type="vitals_trend",
            )
            db.add(alert)
            generated_alerts.append(alert)

    # 4. Drug-Drug Interactions & Polypharmacy
    m_stmt = select(Medicine).where(Medicine.patient_id == patient_id, Medicine.is_active == True)
    m_res = await db.execute(m_stmt)
    active_meds = m_res.scalars().all()
    med_names_set = {m.name.lower().strip() for m in active_meds}

    if len(active_meds) >= 5:
        alert_exists = await _recent_alert_exists(db, patient_id, "polypharmacy", hours=72)
        if not alert_exists:
            alert = PatientAlert(
                patient_id=patient_id,
                severity="info",
                title=f"Polypharmacy Review: {patient.name} is taking {len(active_meds)} concurrent medicines",
                body=f"Patient is currently prescribed {len(active_meds)} active medications. Periodic doctor review recommended.",
                pattern_type="polypharmacy",
            )
            db.add(alert)
            generated_alerts.append(alert)

    # Check drug interaction pairs
    for item in DRUG_INTERACTION_DATABASE:
        if item["pair"].issubset(med_names_set):
            alert_exists = await _recent_alert_exists(db, patient_id, "drug_interaction", hours=48)
            if not alert_exists:
                pair_list = " + ".join([p.capitalize() for p in item["pair"]])
                alert = PatientAlert(
                    patient_id=patient_id,
                    severity=item["severity"],
                    title=f"Potential Drug Interaction: {pair_list}",
                    body=f"Interaction detected between {pair_list}. {item['description']} Surface for doctor review.",
                    pattern_type="drug_interaction",
                )
                db.add(alert)
                generated_alerts.append(alert)

    await db.commit()
    return generated_alerts


async def _recent_alert_exists(db: AsyncSession, patient_id: str, pattern_type: str, hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = select(PatientAlert).where(
        PatientAlert.patient_id == patient_id,
        PatientAlert.pattern_type == pattern_type,
        PatientAlert.created_at >= cutoff,
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none() is not None


async def check_alert_escalations(db: AsyncSession, escalation_window_minutes: int = 15) -> list[PatientAlert]:
    """Find unacknowledged alerts older than escalation_window_minutes and escalate to secondary contacts."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=escalation_window_minutes)

    stmt = select(PatientAlert).where(
        PatientAlert.is_acknowledged == False,
        PatientAlert.is_escalated == False,
        PatientAlert.created_at <= cutoff,
    )
    res = await db.execute(stmt)
    unack_alerts = res.scalars().all()

    escalated = []
    for alert in unack_alerts:
        # Find secondary caregiver for this patient
        links_stmt = select(CaregiverPatient).where(
            CaregiverPatient.patient_id == alert.patient_id,
            CaregiverPatient.role.in_(["secondary", "viewer"]),
        )
        links_res = await db.execute(links_stmt)
        secondary_links = links_res.scalars().all()

        alert.is_escalated = True
        alert.escalated_at = now

        for link in secondary_links:
            # Send notification to secondary caregiver
            notif = Notification(
                user_id=link.user_id,
                patient_id=alert.patient_id,
                notification_type="alert_escalation",
                title=f"[ESCALATED ALERT] {alert.title}",
                body=f"Primary caregiver did not acknowledge within window. {alert.body}",
                related_id=alert.id,
            )
            db.add(notif)
            alert.escalated_to_user_id = link.user_id

        escalated.append(alert)

    await db.commit()
    return escalated
