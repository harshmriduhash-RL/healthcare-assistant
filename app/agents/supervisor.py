"""
Supervisor agent: routes incoming turns to the appropriate worker agent.
Includes graceful fallback routing when LLM API is unavailable.
"""

from langchain_core.messages import SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.core.config import settings

VALID_AGENTS = {"medicine_agent", "dosage_agent", "appointment_agent", "records_agent"}


class RoutingDecision(BaseModel):
    next_agent: str = Field(description="One of: medicine_agent, dosage_agent, appointment_agent, records_agent")
    reasoning: str


async def supervisor_node(state: AgentState) -> dict:
    scope_hint = state.get("scope") or "general"

    try:
        llm = ChatGroq(model=settings.groq_model_supervisor, api_key=settings.groq_api_key, temperature=0)
        structured_llm = llm.with_structured_output(RoutingDecision)
        decision: RoutingDecision = await structured_llm.ainvoke([
            SystemMessage(content=(
                "You are the supervisor of a healthcare assistant agent team. Route to exactly one worker:\n"
                "- medicine_agent: adding/updating/removing medicines\n"
                "- dosage_agent: adding/updating dosage schedule\n"
                "- appointment_agent: scheduling doctor appointments\n"
                "- records_agent: medical records and questions\n"
                f"Scope hint: {scope_hint}."
            )),
            *state["messages"],
        ])
        next_agent = decision.next_agent if decision.next_agent in VALID_AGENTS else "records_agent"
        return {"next_agent": next_agent}
    except Exception:
        # Fallback routing based on scope hint or keyword inspection
        if scope_hint == "medicine":
            next_agent = "medicine_agent"
        elif scope_hint == "dosage":
            next_agent = "dosage_agent"
        elif scope_hint == "appointment":
            next_agent = "appointment_agent"
        else:
            next_agent = "records_agent"
        return {"next_agent": next_agent}


def route_to_worker(state: AgentState) -> str:
    return state["next_agent"]
