"""
The shared LangGraph state schema -- the single "shape of data" that
flows through every node in the agent graph (see app/agents/graph.py for
how the graph is wired).

Every node (supervisor, worker agents, the HITL gate, execute_action)
reads from and writes to this same AgentState dict. This is how, e.g.,
the Medicine Agent's proposed action becomes visible to the HITL node,
and how the human's approve/reject decision becomes visible to
execute_action -- they're all just reading/writing fields on one shared
state object that LangGraph threads through the whole run.
"""

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


class ProposedAction(TypedDict):
    """A single write action a worker agent wants to take, awaiting human
    approval. This is the object that gets shown to the user as an
    "approval card" in the chat UI (see app/templates/chat.html).
    """
    agent: str  # which worker proposed it, e.g. "medicine_agent" -- shown in the approval card's header
    action: str  # e.g. "add_medicine", "update_dosage", "schedule_appointment" -- matches a case in execute_action_node (app/agents/graph.py)
    description: str  # human-readable one-line summary shown in the approval card
    payload: dict[str, Any]  # the structured data the tool will actually execute with, e.g. {"name": "Metformin", "strength": "500mg"}


class AgentState(TypedDict):
    """The full state object threaded through the graph for one turn of
    conversation. LangGraph persists this via the Postgres checkpointer
    (see app/agents/graph.py's get_compiled_graph), which is what lets a
    run PAUSE at the HITL gate and RESUME later from a completely separate
    HTTP request -- the state isn't just in-memory, it survives across
    the pause.
    """
    # `messages` uses LangGraph's `add_messages` reducer, which means new
    # messages get APPENDED to the existing list rather than replacing it
    # wholesale -- this is what makes the conversation history accumulate
    # correctly across multiple turns of the same thread_id.
    messages: Annotated[list, add_messages]

    user_id: str  # whose data this conversation can read/write -- set once at the start of a run and never changed
    thread_id: str  # the conversation's unique id -- matches the LangGraph checkpointer's thread_id and the audit log's thread_id column

    scope: str  # from input guardrails: medicine | dosage | records | appointment | general -- a hint for the supervisor's routing decision
    next_agent: str | None  # the supervisor's routing decision -- which worker node to run next

    proposed_action: ProposedAction | None  # set by a worker agent when it wants to write something; None if nothing is proposed (e.g. the records agent, which never writes)
    approval_decision: Literal["approved", "rejected", "edited", None]  # set by human_approval_node once the human responds
    approval_feedback: str | None  # optional human-provided reason/edit note, shown back to the user on rejection

    final_response: str | None  # the text ultimately shown to the user for this turn -- set by whichever node ends the run (a worker with nothing to propose, execute_action, or rejected_end)
