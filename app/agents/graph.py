"""
LangGraph Multi-Agent Architecture for CarePilot AI with structural Human-in-the-Loop (HITL) guarantees.
"""

from datetime import datetime
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph

from app.agents.hitl import human_approval_node, route_after_approval
from app.agents.state import AgentState
from app.agents.supervisor import route_to_worker, supervisor_node
from app.agents.workers import appointment_agent, dosage_agent, medicine_agent, records_agent
from app.core.config import settings

_ACTION_AGENTS = {"medicine_agent", "dosage_agent", "appointment_agent"}


def needs_approval(state: AgentState) -> str:
    """Conditional edge: route to human approval gate if a write action is proposed."""
    if state.get("proposed_action") is not None:
        return "human_approval"
    return END


async def execute_action_node(state: AgentState) -> dict:
    """The ONLY node permitted to invoke database write tools after HITL approval."""
    from app.core.observability import log_agent_event
    from app.db.session import AsyncSessionLocal
    from app.mcp_servers import postgres_tools

    proposed = state["proposed_action"]
    agent, action, payload = proposed["agent"], proposed["action"], proposed["payload"]
    user_id = state["user_id"]
    patient_id = state.get("patient_id")

    async with AsyncSessionLocal() as db:
        if action == "add_medicine":
            result = await postgres_tools.add_medicine(db, patient_id, user_id, payload["name"], payload.get("strength"), payload.get("notes"))
        elif action == "update_medicine":
            result = await postgres_tools.update_medicine(db, patient_id, payload["medicine_id"], name=payload.get("name"), strength=payload.get("strength"), notes=payload.get("notes"))
        elif action == "remove_medicine":
            result = await postgres_tools.remove_medicine(db, patient_id, payload["medicine_id"])
        elif action == "add_dosage":
            result = await postgres_tools.add_dosage(db, payload["medicine_id"], payload["amount"], payload["frequency"], payload.get("time_of_day"))
        elif action == "update_dosage":
            result = await postgres_tools.update_dosage(db, payload["dosage_id"], amount=payload.get("amount"), frequency=payload.get("frequency"), time_of_day=payload.get("time_of_day"))
        elif action == "remove_dosage":
            result = await postgres_tools.remove_dosage(db, payload["dosage_id"])
        elif action == "schedule_appointment":
            scheduled_for_date = None
            if payload.get("scheduled_for"):
                try:
                    scheduled_for_date = datetime.fromisoformat(payload["scheduled_for"])
                except ValueError:
                    pass

            result = await postgres_tools.schedule_appointment(
                db, patient_id, user_id, payload["doctor_name"], payload.get("specialty"),
                scheduled_for_date, payload.get("notes"),
            )
        elif action == "order_refill":
            result = await postgres_tools.order_pharmacy_refill(
                db, patient_id, payload["medicine_id"], payload.get("quantity", 30), payload.get("partner", "Tata 1mg")
            )
        else:
            result = {"error": f"Unknown action: {action}"}

    async with AsyncSessionLocal() as db:
        await log_agent_event(db, user_id, state["thread_id"], agent, "execute", {"action": action, "result": result, "patient_id": patient_id})

    return {
        "final_response": f"Done — {proposed['description']} ({result})",
        "messages": [AIMessage(content=f"Done — {proposed['description']}")],
    }


def rejected_end_node(state: AgentState) -> dict:
    proposed = state["proposed_action"]
    feedback = state.get("approval_feedback")
    msg = f"Okay, I won't {proposed['description'].lower()}."
    if feedback:
        msg += f" ({feedback})"
    return {"final_response": msg, "messages": [AIMessage(content=msg)]}


def build_graph_definition() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("medicine_agent", medicine_agent)
    graph.add_node("dosage_agent", dosage_agent)
    graph.add_node("appointment_agent", appointment_agent)
    graph.add_node("records_agent", records_agent)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("execute_action", execute_action_node)
    graph.add_node("rejected_end", rejected_end_node)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges("supervisor", route_to_worker, {
        "medicine_agent": "medicine_agent",
        "dosage_agent": "dosage_agent",
        "appointment_agent": "appointment_agent",
        "records_agent": "records_agent",
    })

    for worker in ("medicine_agent", "dosage_agent", "appointment_agent"):
        graph.add_conditional_edges(worker, needs_approval, {"human_approval": "human_approval", END: END})

    graph.add_edge("records_agent", END)

    graph.add_conditional_edges("human_approval", route_after_approval, {
        "execute_action": "execute_action",
        "rejected_end": "rejected_end",
    })
    graph.add_edge("execute_action", END)
    graph.add_edge("rejected_end", END)

    return graph


_compiled_graph = None
_checkpointer_cm = None


async def get_compiled_graph():
    global _compiled_graph, _checkpointer_cm
    if _compiled_graph is not None:
        return _compiled_graph

    _checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url_sync)
    checkpointer = await _checkpointer_cm.__aenter__()
    await checkpointer.setup()

    _compiled_graph = build_graph_definition().compile(checkpointer=checkpointer)
    return _compiled_graph
