"""
Worker agents: the four specialized agents the supervisor routes to.

Each write-capable worker's job is deliberately narrow: read the
conversation, decide what ONE write action (if any) should be proposed,
and set state["proposed_action"]. NONE of them call a database tool
directly -- that only ever happens in app/agents/graph.py's
execute_action_node, and only after human_approval_node (app/agents/hitl.py)
has recorded an "approved" or "edited" decision. This is what makes "no
agent acts without human approval" true structurally, rather than as a
prompt instruction the model could ignore.

The one exception is records_agent at the bottom: it's READ-ONLY (pure
semantic search + answering from retrieved text), so it's allowed to
respond directly without going through the HITL gate at all -- there's
nothing to approve when nothing is being written.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.core.config import settings

_worker_llm = ChatGroq(model=settings.groq_model_worker, api_key=settings.groq_api_key, temperature=0)


# ==================== Medicine agent ====================

class MedicineAction(BaseModel):
    """Structured output shape: forces the model to decide on exactly one
    of a fixed set of actions, rather than returning free text we'd have
    to parse and guess at.
    """
    action: str = Field(description="One of: add_medicine, update_medicine, remove_medicine, none")
    name: str | None = None
    strength: str | None = None
    notes: str | None = None
    medicine_id: str | None = Field(default=None, description="Required for update/remove if known from context")
    description: str = Field(description="One-sentence human-readable summary of the proposed action")


async def medicine_agent(state: AgentState) -> dict:
    """Decides what (if any) medicine-list change the user is asking for,
    and proposes it -- never executes it directly.
    """
    structured_llm = _worker_llm.with_structured_output(MedicineAction)
    result: MedicineAction = await structured_llm.ainvoke([
        SystemMessage(content=(
            "You manage a user's medicine list. Based on the conversation, decide the single "
            "most relevant medicine action to propose. Never invent a medicine_id — leave it null "
            "if you don't have one from the conversation. If nothing actionable, use action='none'."
        )),
        *state["messages"],
    ])

    if result.action == "none":
        # Nothing to propose -- end the turn here with a clarifying
        # message rather than routing to the HITL gate for no reason.
        return {"final_response": "I didn't find a specific medicine change to make. Could you clarify?"}

    # Set proposed_action and STOP -- the graph's edges (see
    # needs_approval() in app/agents/graph.py) will route this to
    # human_approval_node next. This function never touches the database.
    return {
        "proposed_action": {
            "agent": "medicine_agent",
            "action": result.action,
            "description": result.description,
            "payload": {
                "name": result.name, "strength": result.strength,
                "notes": result.notes, "medicine_id": result.medicine_id,
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
    """Decides what (if any) dosage-schedule change the user is asking
    for. Same propose-only pattern as medicine_agent above.
    """
    structured_llm = _worker_llm.with_structured_output(DosageAction)
    result: DosageAction = await structured_llm.ainvoke([
        SystemMessage(content=(
            "You manage dosage schedules for a user's medicines. Propose the single most relevant "
            "dosage action from the conversation. If nothing actionable, use action='none'."
        )),
        *state["messages"],
    ])

    if result.action == "none":
        return {"final_response": "I didn't find a specific dosage change to make. Could you clarify?"}

    return {
        "proposed_action": {
            "agent": "dosage_agent",
            "action": result.action,
            "description": result.description,
            "payload": {
                "medicine_name": result.medicine_name, "amount": result.amount,
                "frequency": result.frequency, "time_of_day": result.time_of_day,
                "dosage_id": result.dosage_id,
            },
        }
    }


# ==================== Appointment agent ====================

class AppointmentAction(BaseModel):
    action: str = Field(description="One of: schedule_appointment, none")
    doctor_name: str | None = None
    specialty: str | None = None
    scheduled_for: str | None = Field(default=None, description="ISO 8601 datetime")
    notes: str | None = None
    description: str


async def appointment_agent(state: AgentState) -> dict:
    """Proposes scheduling an appointment -- but ONLY when the user has
    explicitly asked or clearly granted permission in the conversation.
    This is enforced by the system prompt below (the model is explicitly
    told never to assume consent), which matters because "can schedule an
    appointment if given permission" was a specific requirement -- this
    agent should never take initiative to book something on its own.
    """
    structured_llm = _worker_llm.with_structured_output(AppointmentAction)
    result: AppointmentAction = await structured_llm.ainvoke([
        SystemMessage(content=(
            "You schedule doctor appointments ONLY when the user explicitly asks for one or "
            "explicitly grants permission in this conversation. If the user is just mentioning "
            "a doctor or symptom without asking to schedule, use action='none'. Never assume "
            "consent to schedule."
        )),
        *state["messages"],
    ])

    if result.action == "none":
        return {"final_response": "I won't schedule anything unless you explicitly ask me to. Let me know if you'd like an appointment booked."}

    # --- MOCK AVAILABILITY CHECK ---
    # To demonstrate a complete flow cycle: in a real system, the AI would
    # call an EHR API (Epic/MyChart) or a voice agent (Twilio) to check if 
    # the requested time slot is actually open before proposing the booking.
    if result.scheduled_for:
        import random
        # 20% chance the slot is "taken" to demonstrate the AI pushing back
        is_available = random.random() > 0.2
        if not is_available:
            return {
                "final_response": f"I checked {result.doctor_name or 'the clinic'}'s schedule, and unfortunately, that specific time is not available. Would you like me to find the next open slot?",
                "messages": [AIMessage(content=f"I checked {result.doctor_name or 'the clinic'}'s schedule, and unfortunately, that specific time is not available. Would you like me to find the next open slot?")]
            }

    return {
        "proposed_action": {
            "agent": "appointment_agent",
            "action": result.action,
            "description": result.description,
            "payload": {
                "doctor_name": result.doctor_name, "specialty": result.specialty,
                "scheduled_for": result.scheduled_for, "notes": result.notes,
            },
        }
    }


# ==================== Records / semantic search agent (read-only) ====================

async def records_agent(state: AgentState) -> dict:
    """Answers questions using the user's uploaded medical record PDFs via
    semantic search + retrieval-augmented generation (RAG).

    This is the ONE worker that's allowed to respond directly without
    going through the HITL gate -- it never writes anything to the
    database, it only reads and answers, so there's nothing for a human
    to approve. See app/agents/rag.py for the actual search implementation.
    """
    from app.agents.rag import semantic_search_records

    # Pull the most recent thing the human actually typed (not the
    # assistant's own prior messages) to use as the search query.
    last_user_msg = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    hits = await semantic_search_records(state["user_id"], last_user_msg, top_k=4)

    if not hits:
        return {"final_response": "I couldn't find anything relevant in your uploaded medical records."}

    # Build a context block from the retrieved chunks, tagged with which
    # file each one came from, so the model can (and is instructed to)
    # cite its source rather than blending facts together anonymously.
    context = "\n\n".join(f"[{h['filename']}]: {h['content']}" for h in hits)
    answer = await _worker_llm.ainvoke([
        SystemMessage(content=(
            "Answer the user's question using ONLY the medical record excerpts below. "
            "This is retrieval, not diagnosis — summarize what the records say, don't interpret "
            "clinically. Cite which file each fact came from."
        )),
        HumanMessage(content=f"Records:\n{context}\n\nQuestion: {last_user_msg}"),
    ])

    return {"final_response": answer.content}
