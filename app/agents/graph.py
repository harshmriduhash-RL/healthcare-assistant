"""
Wires every agent node together into one LangGraph StateGraph and compiles
it with a Postgres-backed checkpointer.

THIS FILE IS WHERE "no agent can act without human approval" BECOMES A
STRUCTURAL GUARANTEE rather than a prompt instruction. Read
build_graph_definition() below carefully: notice that execute_action
(the only node that actually calls a database write tool) has exactly
ONE incoming edge, and that edge only fires when human_approval routes to
it via route_after_approval() (app/agents/hitl.py) returning
"execute_action" -- which only happens after a human has recorded
"approved" or "edited". No worker agent node has any edge that leads
anywhere except human_approval (for write-capable workers) or END (for
the read-only records_agent). There is no path through this graph that
reaches a database write without passing through the human approval gate.
"""

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.agents.hitl import human_approval_node, route_after_approval
from app.agents.state import AgentState
from app.agents.supervisor import route_to_worker, supervisor_node
from app.agents.workers import appointment_agent, dosage_agent, medicine_agent, records_agent
from app.core.config import settings

# The three workers whose proposed actions need human approval before
# anything is written. records_agent is deliberately excluded -- it's
# read-only and never proposes an action, so it goes straight to END.
_ACTION_AGENTS = {"medicine_agent", "dosage_agent", "appointment_agent"}


def needs_approval(state: AgentState) -> str:
    """Conditional edge run right after any write-capable worker agent.

    If the worker set a proposed_action, route to the HITL gate. If it
    decided there was nothing to do (action == "none" in the worker's own
    logic, which sets final_response instead), just end the turn --
    there's nothing to approve.
    """
    if state.get("proposed_action") is not None:
        return "human_approval"
    return END


async def execute_action_node(state: AgentState) -> dict:
    """The ONLY node in the entire graph permitted to call a write tool.

    This function only ever runs after human_approval_node has recorded
    an "approved" or "edited" decision (see route_after_approval in
    app/agents/hitl.py) -- there is no other edge into this node. It
    dispatches on `action` to call the matching function in
    app/mcp_servers/postgres_tools.py, which is where the actual SQL
    write happens.
    """
    from app.db.session import AsyncSessionLocal
    from app.mcp_servers import postgres_tools
    from datetime import datetime

    proposed = state["proposed_action"]
    agent, action, payload = proposed["agent"], proposed["action"], proposed["payload"]
    user_id = state["user_id"]

    async with AsyncSessionLocal() as db:
        # Straightforward dispatch table: match the action name the worker
        # agent proposed to the corresponding postgres_tools function,
        # pulling the right fields out of the (possibly human-edited)
        # payload dict for each one.
        if action == "add_medicine":
            result = await postgres_tools.add_medicine(db, user_id, payload["name"], payload.get("strength"), payload.get("notes"))
        elif action == "update_medicine":
            result = await postgres_tools.update_medicine(db, user_id, payload["medicine_id"], name=payload.get("name"), strength=payload.get("strength"), notes=payload.get("notes"))
        elif action == "remove_medicine":
            result = await postgres_tools.remove_medicine(db, user_id, payload["medicine_id"])
        elif action == "add_dosage":
            result = await postgres_tools.add_dosage(db, payload["medicine_id"], payload["amount"], payload["frequency"], payload.get("time_of_day"))
        elif action == "update_dosage":
            result = await postgres_tools.update_dosage(db, payload["dosage_id"], amount=payload.get("amount"), frequency=payload.get("frequency"), time_of_day=payload.get("time_of_day"))
        elif action == "remove_dosage":
            result = await postgres_tools.remove_dosage(db, payload["dosage_id"])
        elif action == "schedule_appointment":
            result = await postgres_tools.schedule_appointment(
                db, user_id, payload["doctor_name"], payload.get("specialty"),
                datetime.fromisoformat(payload["scheduled_for"]), payload.get("notes"),
            )
        else:
            # Should be unreachable given the fixed set of actions worker
            # agents can propose (see the Field descriptions in
            # app/agents/workers.py), but fail loudly rather than silently
            # if it ever happens.
            result = {"error": f"Unknown action: {action}"}

    # Log the execution to the audit trail (powers "View trace" in the UI)
    # in its own separate session, after the write's own session has
    # already committed and closed.
    from app.core.observability import log_agent_event
    async with AsyncSessionLocal() as db:
        await log_agent_event(db, user_id, state["thread_id"], agent, "execute", {"action": action, "result": result})

    return {
        "final_response": f"Done — {proposed['description']} ({result})",
        # Appending an AIMessage keeps the conversation's message history
        # (used by future turns' agent calls) consistent with what was
        # actually shown to the user.
        "messages": [AIMessage(content=f"Done — {proposed['description']}")],
    }


def rejected_end_node(state: AgentState) -> dict:
    """Runs when the human rejects a proposed action. Ends the turn with
    a message confirming nothing was written, optionally including the
    human's stated reason.
    """
    proposed = state["proposed_action"]
    feedback = state.get("approval_feedback")
    msg = f"Okay, I won't {proposed['description'].lower()}."
    if feedback:
        msg += f" ({feedback})"
    return {"final_response": msg, "messages": [AIMessage(content=msg)]}


def build_graph_definition() -> StateGraph:
    """Construct the graph's nodes and edges. Called once by
    get_compiled_graph() below; kept as a separate function so the graph
    STRUCTURE (easy to read top-to-bottom) is decoupled from the
    checkpointer SETUP (which needs an async context and only needs to
    happen once per process).
    """
    graph = StateGraph(AgentState)

    # --- Register every node ---
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("medicine_agent", medicine_agent)
    graph.add_node("dosage_agent", dosage_agent)
    graph.add_node("appointment_agent", appointment_agent)
    graph.add_node("records_agent", records_agent)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("execute_action", execute_action_node)
    graph.add_node("rejected_end", rejected_end_node)

    # --- Wire the edges ---

    # Every run starts at the supervisor, which decides the route.
    graph.set_entry_point("supervisor")
    graph.add_conditional_edges("supervisor", route_to_worker, {
        "medicine_agent": "medicine_agent",
        "dosage_agent": "dosage_agent",
        "appointment_agent": "appointment_agent",
        "records_agent": "records_agent",
    })

    # THE SAFETY-CRITICAL PART: every write-capable worker's only possible
    # next step is either the HITL gate (if it proposed something) or END
    # (if it decided there was nothing to do). None of them have a direct
    # edge to execute_action -- that edge only exists FROM human_approval.
    for worker in ("medicine_agent", "dosage_agent", "appointment_agent"):
        graph.add_conditional_edges(worker, needs_approval, {"human_approval": "human_approval", END: END})

    # records_agent is read-only (never sets proposed_action), so it goes
    # straight to END -- correctly bypassing the approval gate, since
    # there's nothing to approve when nothing is being written.
    graph.add_edge("records_agent", END)

    # After the human responds (human_approval_node returns), route based
    # on their decision -- this is the ONLY edge in the whole graph that
    # leads to execute_action.
    graph.add_conditional_edges("human_approval", route_after_approval, {
        "execute_action": "execute_action",
        "rejected_end": "rejected_end",
    })
    graph.add_edge("execute_action", END)
    graph.add_edge("rejected_end", END)

    return graph


# Module-level cache so the graph is only built and compiled once per
# process, not on every single chat request.
_compiled_graph = None
_checkpointer_cm = None


async def get_compiled_graph():
    """Lazily build, compile, and cache the graph with a Postgres-backed
    checkpointer.

    The checkpointer is what makes interrupt()/resume actually survive
    across separate HTTP requests: without it, LangGraph's state would
    only live in memory for the duration of one .ainvoke() call, and a
    paused graph would be lost the moment that call returns. With it,
    the graph's exact paused state (including which node it stopped at
    and everything in AgentState) is durably saved to Postgres, keyed by
    thread_id -- so /api/chat/start can pause mid-run, return a response,
    and /api/chat/resume can pick that EXACT run back up later, even from
    a different request or a different server process.
    """
    global _compiled_graph, _checkpointer_cm
    if _compiled_graph is not None:
        return _compiled_graph

    # AsyncPostgresSaver needs its own connection to Postgres (separate
    # from the app's main SQLAlchemy engine) since it manages its own
    # checkpoint tables directly via psycopg. from_conn_string(...) gives
    # us an async context manager; __aenter__() opens the connection.
    _checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url_sync)
    checkpointer = await _checkpointer_cm.__aenter__()
    # Creates the checkpointer's own tables in Postgres if they don't
    # already exist (separate from our own Alembic-managed tables) --
    # must run before the graph can be compiled with this checkpointer.
    await checkpointer.setup()

    _compiled_graph = build_graph_definition().compile(checkpointer=checkpointer)
    return _compiled_graph
