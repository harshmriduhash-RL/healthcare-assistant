"""
The chat API: starts new agent conversations and resumes ones paused at
the human-approval gate.

This file is the HTTP-facing half of the human-in-the-loop mechanism --
app/agents/hitl.py's interrupt() call is the graph-side half. Together
they implement a request/response cycle that can span multiple, entirely
separate HTTP calls:

  1. Browser POSTs /api/chat/start with a message.
  2. The agent graph runs until it either finishes, or hits
     human_approval_node's interrupt() and pauses.
  3. If paused, this route returns the pending approval request to the
     browser and the HTTP request ends -- but the graph run itself is
     NOT finished, it's frozen mid-execution, its state saved by the
     Postgres checkpointer (see app/agents/graph.py).
  4. Later (seconds or hours after), the browser POSTs /api/chat/resume
     with the human's decision. This route resumes the EXACT SAME paused
     graph run from exactly where it left off.
"""

import uuid

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_compiled_graph
from app.core.deps import get_current_user
from app.core.observability import log_agent_event
from app.core.schemas import ChatRequest, ResumeRequest
from app.db.models import User
from app.db.session import get_db
from app.guardrails.input_guardrails import run_input_guardrails

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _interrupt_payload(state_snapshot):
    """Pull the pending interrupt (if any) out of a graph state snapshot.

    A LangGraph state snapshot's `.interrupts` list is non-empty exactly
    when the graph is currently paused at an interrupt() call -- this
    small helper is used by both /start and /resume to check "did we just
    stop at the HITL gate?" and, if so, extract the payload we passed to
    interrupt() in human_approval_node (app/agents/hitl.py) so it can be
    sent to the browser to render the approval card.
    """
    if state_snapshot.interrupts:
        return state_snapshot.interrupts[0].value
    return None


@router.post("/start")
async def start_chat(payload: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Start a new turn of conversation (or continue an existing thread if
    thread_id was passed).
    """
    # A fresh conversation gets a new random thread_id; an ongoing one
    # reuses the id the browser already has, so the LangGraph checkpointer
    # (and the audit log) can find the right prior state/history.
    thread_id = payload.thread_id or str(uuid.uuid4())

    # STEP 1: guardrails run BEFORE the agent graph is even invoked. See
    # app/guardrails/input_guardrails.py for what this checks.
    guardrail_result = await run_input_guardrails(payload.message)
    await log_agent_event(db, user.id, thread_id, "input_guardrail", "guardrail_check", {
        "allowed": guardrail_result.allowed, "reason": guardrail_result.reason, "scope": guardrail_result.scope,
    })

    if not guardrail_result.allowed:
        # Blocked message -- the agent graph never runs at all for this
        # turn. The browser shows guardrail_result.reason directly to the
        # user (see the "system-blocked" message style in chat.html).
        return {"thread_id": thread_id, "status": "blocked", "message": guardrail_result.reason}

    graph = await get_compiled_graph()
    # LangGraph's checkpointer keys all state by this "configurable"
    # thread_id -- every .ainvoke()/.aget_state() call for this
    # conversation must pass the SAME thread_id to find the right history.
    config = {"configurable": {"thread_id": thread_id}}

    # Kick off the graph run with a freshly-initialized AgentState. Every
    # field from app/agents/state.py's AgentState TypedDict must be
    # present here for the first invocation of a new thread.
    result = await graph.ainvoke({
        "messages": [HumanMessage(content=payload.message)],
        "user_id": user.id,
        "thread_id": thread_id,
        "scope": guardrail_result.scope,
        "next_agent": None,
        "proposed_action": None,
        "approval_decision": None,
        "approval_feedback": None,
        "final_response": None,
    }, config=config)

    # After ainvoke() returns, check whether the run actually finished, or
    # paused at the HITL gate. Note: `result` above already reflects
    # whatever the graph returned when it stopped (either at END or at an
    # interrupt) -- we still need aget_state() separately to check for
    # and extract a pending interrupt payload.
    snapshot = await graph.aget_state(config)
    interrupt_payload = _interrupt_payload(snapshot)

    if interrupt_payload:
        # The graph is now PAUSED. Log the proposal to the audit trail and
        # send the approval card details to the browser. The HTTP request
        # ends here, but the graph run itself does not -- it's waiting.
        await log_agent_event(db, user.id, thread_id, interrupt_payload["agent"], "propose", interrupt_payload)
        return {"thread_id": thread_id, "status": "pending_approval", "approval_request": interrupt_payload}

    # No interrupt hit -- the turn completed fully in one shot (e.g. the
    # records_agent path, or a worker that decided there was nothing to
    # propose). final_response was set by whichever node ended the run.
    return {"thread_id": thread_id, "status": "complete", "message": result.get("final_response")}


@router.post("/resume")
async def resume_chat(payload: ResumeRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Resume a graph run that's currently paused at the HITL gate, with
    the human's decision.
    """
    graph = await get_compiled_graph()
    config = {"configurable": {"thread_id": payload.thread_id}}

    # This dict's shape must match what human_approval_node
    # (app/agents/hitl.py) expects to receive back from interrupt() --
    # it becomes that call's return value the moment the graph resumes.
    resume_value = {
        "decision": payload.decision,
        "feedback": payload.feedback,
        "payload": payload.edited_payload,
    }

    await log_agent_event(db, user.id, payload.thread_id, "human", payload.decision, resume_value)

    # Command(resume=...) is LangGraph's mechanism for continuing a graph
    # run from exactly the interrupt() call it paused at -- NOT starting a
    # new run. The graph picks back up inside human_approval_node with
    # interrupt(...) now returning resume_value, then continues on to
    # execute_action or rejected_end depending on the decision.
    result = await graph.ainvoke(Command(resume=resume_value), config=config)

    # It's possible (though not expected in this app's current graph
    # shape) for a resumed run to hit ANOTHER interrupt before finishing --
    # this check handles that generally rather than assuming exactly one
    # approval per conversation turn.
    snapshot = await graph.aget_state(config)
    interrupt_payload = _interrupt_payload(snapshot)
    if interrupt_payload:
        return {"thread_id": payload.thread_id, "status": "pending_approval", "approval_request": interrupt_payload}

    return {"thread_id": payload.thread_id, "status": "complete", "message": result.get("final_response")}


@router.get("/trace/{thread_id}")
async def get_trace(thread_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return the full audit trail for one conversation thread, in
    chronological order. Powers the "View trace" button in the chat UI.
    Scoped to `user.id` so a user can only ever view their own
    conversations' traces, even if they somehow guessed another thread_id.
    """
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
