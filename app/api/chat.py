"""
The chat API: starts new agent conversations and resumes ones paused at the human-approval gate.
Now patient-context aware for CarePilot AI.
"""

import uuid

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_compiled_graph
from app.core.deps import get_current_patient_context, get_current_user
from app.core.observability import log_agent_event
from app.core.schemas import ChatRequest, ResumeRequest
from app.db.models import Patient, User
from app.db.session import get_db
from app.guardrails.input_guardrails import run_input_guardrails

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _interrupt_payload(state_snapshot):
    if state_snapshot.tasks:
        for task in state_snapshot.tasks:
            if task.interrupts:
                return task.interrupts[0].value
    return None


@router.post("/start")
async def start_chat(
    payload: ChatRequest,
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new turn of conversation scoped to the active patient."""
    thread_id = payload.thread_id or str(uuid.uuid4())

    guardrail_result = await run_input_guardrails(payload.message)
    await log_agent_event(db, user.id, thread_id, "input_guardrail", "guardrail_check", {
        "allowed": guardrail_result.allowed, "reason": guardrail_result.reason, "scope": guardrail_result.scope, "patient_id": patient.id,
    })

    if not guardrail_result.allowed:
        return {"thread_id": thread_id, "status": "blocked", "message": guardrail_result.reason}

    graph = await get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}

    result = await graph.ainvoke({
        "messages": [HumanMessage(content=payload.message)],
        "user_id": user.id,
        "patient_id": patient.id,
        "thread_id": thread_id,
        "scope": guardrail_result.scope,
        "next_agent": None,
        "proposed_action": None,
        "approval_decision": None,
        "approval_feedback": None,
        "final_response": None,
    }, config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = _interrupt_payload(snapshot)

    if interrupt_payload:
        await log_agent_event(db, user.id, thread_id, interrupt_payload["agent"], "propose", interrupt_payload)
        return {"thread_id": thread_id, "status": "pending_approval", "approval_request": interrupt_payload}

    return {"thread_id": thread_id, "status": "complete", "message": result.get("final_response")}


@router.post("/resume")
async def resume_chat(
    payload: ResumeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a graph run paused at the HITL approval gate."""
    graph = await get_compiled_graph()
    config = {"configurable": {"thread_id": payload.thread_id}}

    resume_value = {
        "decision": payload.decision,
        "feedback": payload.feedback,
        "payload": payload.edited_payload,
    }

    await log_agent_event(db, user.id, payload.thread_id, "human", payload.decision, resume_value)

    result = await graph.ainvoke(Command(resume=resume_value), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = _interrupt_payload(snapshot)
    if interrupt_payload:
        return {"thread_id": payload.thread_id, "status": "pending_approval", "approval_request": interrupt_payload}

    return {"thread_id": payload.thread_id, "status": "complete", "message": result.get("final_response")}


@router.get("/trace/{thread_id}")
async def get_trace(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full audit trail for one conversation thread."""
    from sqlalchemy import select
    from app.db.models import AgentAuditLog

    result = await db.execute(
        select(AgentAuditLog)
        .where(AgentAuditLog.thread_id == thread_id, AgentAuditLog.user_id == user.id)
        .order_by(AgentAuditLog.created_at.asc())
    )
    rows = result.scalars().all()
    return [
        {
            "agent": r.agent_name, "action_type": r.action_type, "payload": r.payload,
            "latency_ms": r.latency_ms, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
