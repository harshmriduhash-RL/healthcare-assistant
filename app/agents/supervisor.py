"""
The supervisor agent: the entry point of the graph for every message that
passes the input guardrails. Its ONLY job is routing -- deciding which
one of the four worker agents (see app/agents/workers.py) should handle
this turn. It never proposes an action itself and never talks to the
database.

This is what makes the system genuinely "multi-agent" rather than one
big prompt: each worker below has a narrow, focused job and its own
system prompt, and the supervisor's job is just picking the right one
based on the conversation.
"""

from langchain_core.messages import SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.core.config import settings

# Uses the "worker"-tier model (see app/core/config.py) since routing is a
# reasoning task that benefits from a stronger model, unlike the
# guardrail's lightweight classification.
_supervisor_llm = ChatGroq(model=settings.groq_model_supervisor, api_key=settings.groq_api_key, temperature=0)

# The only agent names the supervisor is allowed to route to -- used as a
# safety net below in case the LLM returns something unexpected.
VALID_AGENTS = {"medicine_agent", "dosage_agent", "appointment_agent", "records_agent"}


class RoutingDecision(BaseModel):
    """Structured output shape for the supervisor's routing call."""
    next_agent: str = Field(description="One of: medicine_agent, dosage_agent, appointment_agent, records_agent")
    reasoning: str  # not used programmatically, but forcing the model to state its reasoning tends to improve routing accuracy


async def supervisor_node(state: AgentState) -> dict:
    """Decide which single worker agent handles this conversation turn."""
    # The input guardrail (app/guardrails/input_guardrails.py) already did
    # a rough scope classification before this node ever ran -- we pass
    # that along as a hint, but the supervisor makes the FINAL call using
    # the full conversation history, since scope alone can't disambiguate
    # everything: e.g. "update my metformin dosage" is a dosage_agent
    # request, but "I'm switching from metformin to a different drug" is a
    # medicine_agent request, even though both mention "metformin."
    structured_llm = _supervisor_llm.with_structured_output(RoutingDecision)
    decision: RoutingDecision = await structured_llm.ainvoke([
        SystemMessage(content=(
            "You are the supervisor of a healthcare assistant's agent team. Route the "
            "conversation to exactly one worker agent:\n"
            "- medicine_agent: adding/updating/removing a medicine from the user's list\n"
            "- dosage_agent: adding/updating/removing dosage/schedule info for an existing medicine\n"
            "- appointment_agent: scheduling a doctor appointment (only if user explicitly asked)\n"
            "- records_agent: answering questions about uploaded medical records, or searching them\n"
            f"The input guardrail already classified this message's scope as: {state.get('scope')}. "
            "Use that as a strong hint but make the final call based on the full conversation."
        )),
        *state["messages"],  # the full conversation so far, unpacked as individual messages for the LLM call
    ])

    # Defensive fallback: if the model somehow returns something outside
    # our four known agents (shouldn't happen with structured output, but
    # models can occasionally still misbehave), default to the read-only
    # records_agent rather than crashing or routing to an agent that could
    # attempt a write based on a malformed decision.
    next_agent = decision.next_agent if decision.next_agent in VALID_AGENTS else "records_agent"
    return {"next_agent": next_agent}


def route_to_worker(state: AgentState) -> str:
    """Conditional edge function LangGraph calls to decide which node to
    run next, based on what supervisor_node just decided.
    """
    return state["next_agent"]
