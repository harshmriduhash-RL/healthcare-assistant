"""
Shared LangGraph state schema for CarePilot AI multi-agent workflow.
"""

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


class ProposedAction(TypedDict):
    """A single write action a worker agent wants to take, awaiting human approval."""
    agent: str  # which worker proposed it
    action: str  # e.g., "add_medicine", "update_dosage", "schedule_appointment", "order_refill"
    description: str  # human-readable summary
    payload: dict[str, Any]  # structured arguments


class AgentState(TypedDict):
    """Full state object threaded through the graph for one turn of conversation."""
    messages: Annotated[list, add_messages]
    user_id: str  # Caregiver ID
    patient_id: str  # Active Patient ID
    thread_id: str

    scope: str
    next_agent: str | None

    proposed_action: ProposedAction | None
    approval_decision: Literal["approved", "rejected", "edited", None]
    approval_feedback: str | None

    final_response: str | None
