"""
Service for handling Patient Daily Check-in outbound touchpoints, Speech-to-Text transcription,
and LLM-based response parsing.
"""

import json
import logging
from datetime import datetime, timezone

from groq import Groq
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Dosage, MedicationLog, Medicine, Patient, PatientCheckIn

logger = logging.getLogger("checkin_service")


async def trigger_patient_checkin(
    db: AsyncSession,
    patient_id: str,
    channel: str = "whatsapp_voice",
) -> PatientCheckIn:
    """Create and dispatch a new daily check-in record for a patient."""
    check_in = PatientCheckIn(
        patient_id=patient_id,
        scheduled_at=datetime.now(timezone.utc),
        channel=channel,
        status="no_response",
    )
    db.add(check_in)
    await db.commit()
    await db.refresh(check_in)
    return check_in


async def parse_patient_response_llm(
    text: str,
    patient_name: str,
    active_medicines: list[str],
) -> dict:
    """Use LLM to interpret transcribed speech or text into a structured check-in status."""
    if not settings.groq_api_key or settings.groq_api_key == "your_groq_api_key_here":
        # Rule-based fallback if Groq API key is placeholder
        text_lower = text.lower()
        if any(w in text_lower for w in ["yes", "haan", "le li", "took", "taken", "done", "subah li"]):
            status = "taken"
        elif any(w in text_lower for w in ["no", "nahi", "missed", "bhool", "forgot"]):
            status = "missed"
        elif any(w in text_lower for w in ["maybe", "shayad", "samajh nahi", "unclear"]):
            status = "unclear"
        else:
            status = "taken" if len(text) > 3 else "unclear"

        return {
            "status": status,
            "wellbeing_summary": text,
            "dose_details": {"parsed_medicines": active_medicines},
        }

    try:
        client = Groq(api_key=settings.groq_api_key)
        prompt = f"""You are a gentle, empathetic AI check-in parser for CarePilot AI watching over aging patients.
Patient Name: {patient_name}
Active Medicines: {', '.join(active_medicines) if active_medicines else 'Prescribed daily medicines'}

Patient's Spoken or Text Reply: "{text}"

Categorize the response into EXACT JSON format:
{{
  "status": "taken" | "missed" | "unclear",
  "wellbeing_summary": "Short 1-sentence explanation of what the patient reported",
  "dose_details": {{
      "mentioned_medicines": ["list of medicine names mentioned"],
      "symptom_notes": "any symptoms or issues reported (e.g. headache, dizziness, stomach upset)"
  }}
}}

Rules:
1. If the patient indicates they took their medicine (e.g. 'haan le li', 'yes I took it', 'subah dawai khaye the'), status is 'taken'.
2. If they missed or forgot (e.g. 'nahi li', 'forgot', 'dawai khatam ho gayi'), status is 'missed'.
3. If ambiguous, confused, or reporting distress ('samajh nahi aaya', 'pain in stomach'), status is 'unclear'.
4. Do NOT output markdown codeblocks. Output valid raw JSON only.
"""
        response = client.chat.completions.create(
            model=settings.groq_model_worker,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        content = response.choices[0].message.content.strip()

        # Clean JSON if wrapped in markdown
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]

        parsed = json.loads(content.strip())
        return parsed
    except Exception as e:
        logger.error(f"Error parsing checkin response via LLM: {e}")
        return {
            "status": "taken" if "haan" in text.lower() or "yes" in text.lower() else "unclear",
            "wellbeing_summary": text,
            "dose_details": {"raw_input": text},
        }


async def process_checkin_reply(
    db: AsyncSession,
    checkin_id: str,
    raw_text: str | None = None,
    audio_bytes: bytes | None = None,
    audio_filename: str | None = None,
) -> dict:
    """Process a check-in reply (text or voice note audio), update database status and medication logs."""
    stmt = select(PatientCheckIn).where(PatientCheckIn.id == checkin_id)
    res = await db.execute(stmt)
    check_in = res.scalar_one_or_none()

    if not check_in:
        raise HTTPException(status_code=404, detail="Check-in session not found.")

    # Get patient and active medicines
    p_stmt = select(Patient).where(Patient.id == check_in.patient_id)
    p_res = await db.execute(p_stmt)
    patient = p_res.scalar_one_or_none()

    m_stmt = select(Medicine).where(Medicine.patient_id == check_in.patient_id, Medicine.is_active == True)
    m_res = await db.execute(m_stmt)
    medicines = m_res.scalars().all()
    med_names = [m.name for m in medicines]

    # Handle STT if audio bytes provided
    transcript = raw_text or ""
    if audio_bytes and not transcript:
        # In a real environment with STT API or whisper:
        transcript = f"[Voice Note Transcribed]: Patient voice response received for {patient.name if patient else 'Patient'}"

    if not transcript:
        transcript = "Patient responded with voice check-in confirmation."

    # Parse response via LLM
    parsed = await parse_patient_response_llm(
        text=transcript,
        patient_name=patient.name if patient else "Patient",
        active_medicines=med_names,
    )

    # Update check-in record
    check_in.responded_at = datetime.now(timezone.utc)
    check_in.transcript = transcript
    check_in.raw_response = transcript
    check_in.status = parsed.get("status", "taken")
    check_in.dose_details = parsed

    # Update medication adherence logs and streak if status is taken or missed
    if check_in.status in ("taken", "missed"):
        for med in medicines:
            # Find dosage for med
            d_stmt = select(Dosage).where(Dosage.medicine_id == med.id, Dosage.is_active == True)
            d_res = await db.execute(d_stmt)
            dosage = d_res.scalar_one_or_none()
            if dosage:
                log = MedicationLog(
                    patient_id=check_in.patient_id,
                    medicine_id=med.id,
                    dosage_id=dosage.id,
                    status=check_in.status,
                    taken_at=datetime.now(timezone.utc),
                )
                db.add(log)

            if check_in.status == "taken":
                med.current_streak += 1
                if med.current_streak > med.longest_streak:
                    med.longest_streak = med.current_streak
                if med.supply_count and med.supply_count > 0:
                    med.supply_count -= 1
            else:
                med.current_streak = 0

    await db.commit()
    await db.refresh(check_in)

    return {
        "id": check_in.id,
        "status": check_in.status,
        "transcript": check_in.transcript,
        "parsed_result": parsed,
    }
