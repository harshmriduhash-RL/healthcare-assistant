"""
The Human-in-the-Loop gate: the single chokepoint every write action must
pass through, and the core safety mechanism of the whole system.

No worker agent (medicine_agent, dosage_agent, appointment_agent -- see
app/agents/workers.py) EVER calls a write tool directly. Instead, a
worker's only job is to decide WHAT it wants to do and set
`state["proposed_action"]`, then the graph routes to THIS node. This node
calls LangGraph's `interrupt()`, which pauses the ENTIRE graph execution
right here and hands control back to whoever called `.ainvoke()` -- in
our case, the FastAPI route in app/api/chat.py, which returns the
proposed action to the browser as a pending "approval request." The
graph then stays paused (its state is durably saved by the Postgres
checkpointer) until /api/chat/resume is called with the human's decision,
which can happen much later and from a totally separate HTTP request.

Because this is the ONLY node that can turn a proposed_action into an
approved one, "no agent can act without human approval" is enforced by
the shape of the graph itself (see app/agents/graph.py's edges), not by
convention or by trusting the LLM to follow an instruction.
"""

from langgraph.types import interrupt

from app.agents.state import AgentState


def human_approval_node(state: AgentState) -> dict:
    """The interrupt point. Runs once a worker agent has proposed a write
    action, and pauses execution until a human responds.
    """
    proposed = state["proposed_action"]
    if proposed is None:
        # Defensive fallback -- shouldn't normally happen, since the graph
        # only routes here when a worker set proposed_action (see
        # needs_approval() in app/agents/graph.py), but guards against a
        # worker bug that routes here without actually proposing anything.
        return {"approval_decision": None}

    # interrupt(...) does two things at once:
    #   1. Pauses graph execution AT THIS EXACT POINT -- nothing after this
    #      line runs until the graph is explicitly resumed.
    #   2. The dict passed in becomes the "interrupt payload" that the
    #      caller (app/api/chat.py) reads via graph.aget_state(config) and
    #      sends to the browser to render as an approval card.
    # When the graph is later resumed via Command(resume=<value>), THIS
    # call to interrupt() returns <value> -- that's how human_response
    # below gets populated on the second run.
    human_response = interrupt({
        "type": "approval_request",
        "agent": proposed["agent"],
        "action": proposed["action"],
        "description": proposed["description"],
        "payload": proposed["payload"],
    })

    # Expected shape of human_response (built in app/api/chat.py's
    # resume_chat route from the ResumeRequest the browser sent):
    #   {"decision": "approved"|"rejected"|"edited", "feedback": str|None, "payload": dict|None}
    decision = human_response.get("decision", "rejected")  # default to rejected if somehow missing -- fail closed, not open

    if decision == "edited" and human_response.get("payload"):
        # The human used the "Edit" button in the chat UI to change the
        # proposed values before approving -- replace the agent's original
        # payload with the human-edited one. This is what makes "Save &
        # Approve" write the CORRECTED values, not the agent's original guess.
        proposed = {**proposed, "payload": human_response["payload"]}

    return {
        "proposed_action": proposed,  # possibly updated with edited payload
        "approval_decision": decision,
        "approval_feedback": human_response.get("feedback"),
    }


def route_after_approval(state: AgentState) -> str:
    """Conditional edge function: after the human decides, either go
    execute the now-approved action, or end the turn having done nothing.

    "edited" is treated the same as "approved" here -- editing IS a form
    of approval, just with corrected values (the correction already
    happened above, before this function runs).
    """
    if state.get("approval_decision") in ("approved", "edited"):
        return "execute_action"
    return "rejected_end"
