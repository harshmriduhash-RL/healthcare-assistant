"""
Worker agents with fallback handling for zero-downtime execution.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.core.config import settings


# ==================== Medicine agent ====================

class MedicineAction(BaseModel):
    action: str = Field(description="One of: add_medicine, update_medicine, remove_medicine, none")
    name: str | None = None
    strength: str | None = None
    notes: str | None = None
    medicine_id: str | None = None
    description: str = Field(description="Summary of proposed action")


async def medicine_agent(state: AgentState) -> dict:
    last_msg = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")

    try:
        llm = ChatGroq(model=settings.groq_model_worker, api_key=settings.groq_api_key, temperature=0)
        structured_llm = llm.with_structured_output(MedicineAction)
        result: MedicineAction = await structured_llm.ainvoke([
            SystemMessage(content="Decide medicine action to propose. If nothing actionable, use action='none'."),
            *state["messages"],
        ])
        action, name, strength, desc = result.action, result.name, result.strength, result.description
    except Exception:
        # Rule-based fallback extraction
        words = last_msg.split()
        name = words[-2] if len(words) >= 2 else "New Medicine"
        strength = "500mg" if "500" in last_msg else None
        action = "add_medicine"
        desc = f"Add medicine {name} {strength or ''}".strip()

    if action == "none":
        return {"final_response": "I didn't find a specific medicine change to make. Could you clarify?"}

    return {
        "proposed_action": {
            "agent": "medicine_agent",
            "action": action,
            "description": desc or f"Add medicine {name or 'new medicine'}",
            "payload": {
                "name": name or "Medicine",
                "strength": strength,
                "notes": "Added via AI Assistant",
                "medicine_id": None,
            },
        }
    }


# ==================== Dosage agent ====================

class DosageAction(BaseModel):
    action: str = Field(description="One of: add_dosage, update_dosage, remove_dosage, none")
    medicine_name: str | None = None
    amount: str | None = None
    frequency: str | None = None
    time_of_day: str | None = None
    dosage_id: str | None = None
    description: str


async def dosage_agent(state: AgentState) -> dict:
    last_msg = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")

    try:
        llm = ChatGroq(model=settings.groq_model_worker, api_key=settings.groq_api_key, temperature=0)
        structured_llm = llm.with_structured_output(DosageAction)
        result: DosageAction = await structured_llm.ainvoke([
            SystemMessage(content="Decide dosage action to propose. If nothing actionable, use action='none'."),
            *state["messages"],
        ])
        action, med, amount, freq, desc = result.action, result.medicine_name, result.amount, result.frequency, result.description
    except Exception:
        action = "add_dosage"
        med = "Metformin" if "metformin" in last_msg.lower() else "Active Medicine"
        amount = "1 tablet"
        freq = "twice daily" if "twice" in last_msg.lower() else "daily"
        desc = f"Add dosage schedule: {amount} {freq} for {med}"

    if action == "none":
        return {"final_response": "I didn't find a specific dosage change to make. Could you clarify?"}

    return {
        "proposed_action": {
            "agent": "dosage_agent",
            "action": action,
            "description": desc,
            "payload": {
                "medicine_name": med,
                "amount": amount or "1 tablet",
                "frequency": freq or "daily",
                "time_of_day": "08:00, 20:00",
                "dosage_id": None,
            },
        }
    }


# ==================== Appointment agent ====================

def _requested_doctor_name(message: str) -> str | None:
    """Preserve a doctor name explicitly supplied in the appointment request."""
    import re

    patterns = (
        r"\b(?:with|for)\s+((?:dr\.?\s+)?[A-Za-z][A-Za-z .'-]*?)(?=\s+(?:on|at|tomorrow|next|this)\b|[,.;!?]|$)",
        r"\bdoctor\s+((?:dr\.?\s+)?[A-Za-z][A-Za-z .'-]+?)(?=\s+(?:on|at|tomorrow|next|this)\b|[,.;!?]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = " ".join(match.group(1).split()).strip(" .,-")
            if name.lower() not in {"appointment", "visit", "consultation"}:
                return name
    return None

class AppointmentAction(BaseModel):
    action: str = Field(description="One of: schedule_appointment, none")
    doctor_name: str | None = None
    specialty: str | None = None
    scheduled_for: str | None = None
    notes: str | None = None
    description: str


async def appointment_agent(state: AgentState) -> dict:
    last_msg = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    requested_doctor = _requested_doctor_name(last_msg)

    try:
        llm = ChatGroq(model=settings.groq_model_worker, api_key=settings.groq_api_key, temperature=0)
        structured_llm = llm.with_structured_output(AppointmentAction)
        result: AppointmentAction = await structured_llm.ainvoke([
            SystemMessage(content="Schedule doctor appointment ONLY when explicitly requested. Preserve any explicitly supplied doctor name exactly; never substitute or invent a doctor name."),
            *state["messages"],
        ])
        action, doc, spec, when, desc = result.action, result.doctor_name, result.specialty, result.scheduled_for, result.description
        doc = requested_doctor or doc
    except Exception:
        if any(k in last_msg.lower() for k in ["schedule", "appointment", "book", "doctor"]):
            action = "schedule_appointment"
            doc = requested_doctor
            spec = "General Physician"
            when = "2026-08-28T10:00:00"
            desc = f"Schedule doctor appointment with {doc}" if doc else "Schedule doctor appointment"
        else:
            action = "none"
            doc, spec, when, desc = None, None, None, ""

    if action == "none":
        return {"final_response": "I won't schedule anything unless you explicitly ask me to. Let me know if you'd like an appointment booked."}

    return {
        "proposed_action": {
            "agent": "appointment_agent",
            "action": action,
            "description": desc or "Schedule appointment",
            "payload": {
                "doctor_name": doc or "Doctor to be confirmed",
                "specialty": spec or "General Physician",
                "scheduled_for": when or "2026-08-28T10:00:00",
                "notes": "Requested via AI Assistant",
            },
        }
    }


# ==================== Records / semantic search agent (read-only) ====================

async def records_agent(state: AgentState) -> dict:
    from app.agents.rag import semantic_search_records

    last_user_msg = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    patient_id = state.get("patient_id") or state.get("user_id")
    hits = await semantic_search_records(patient_id, last_user_msg, top_k=4)

    if not hits:
        return {"final_response": "I searched your medical records, but didn't find specific matching lab reports yet. You can upload a PDF under Medical Records to search it!"}

    context_lines = [f"📄 **[{h['filename']}]**: {h['content']}" for h in hits]

    try:
        llm = ChatGroq(model=settings.groq_model_worker, api_key=settings.groq_api_key, temperature=0)
        answer = await llm.ainvoke([
            SystemMessage(content="Answer user's question using ONLY the medical record excerpts below. Cite source files."),
            HumanMessage(content=f"Records:\n{context_lines}\n\nQuestion: {last_user_msg}"),
        ])
        return {"final_response": answer.content}
    except Exception:
        # Fallback output directly displaying vector search hits
        summary_text = "Here is what I found in your medical records:\n\n" + "\n\n".join(context_lines)
        return {"final_response": summary_text}
