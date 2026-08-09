"""
A REAL MCP (Model Context Protocol) server, exposing a subset of the
write tools from postgres_tools.py over the actual MCP protocol via
stdio (standard input/output) -- the same transport real third-party MCP
servers (e.g. a Slack or GitHub MCP server) use.

This exists to make the "MCP" part of the tech stack genuine rather than
just a naming convention: the tool implementations in postgres_tools.py
ARE the source of truth, and this file just wraps them behind MCP's
standard `list_tools`/`call_tool` interface so any MCP-compatible client
(not just this specific LangGraph app) could discover and call them.

Run standalone:  python -m app.mcp_servers.mcp_stdio_server

NOT used by the main app by default -- app/agents/graph.py's
execute_action_node calls postgres_tools.py functions directly, in-process,
for lower latency during a live demo. To actually route agent tool calls
through THIS server instead, you'd use langchain-mcp-adapters'
MultiServerMCPClient to load these as LangChain tools and swap them in
where workers.py/graph.py currently import from postgres_tools directly.
"""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from app.db.session import AsyncSessionLocal
from app.mcp_servers import postgres_tools

# The MCP server object itself -- "healthcare-postgres-tools" is its
# name as it would appear to an MCP client that connects to it.
server = Server("healthcare-postgres-tools")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """MCP's discovery endpoint: tells any connecting client what tools
    this server offers and what arguments each one expects (as JSON
    Schema). Only two tools are wired up here as a demonstration --
    add_medicine and schedule_appointment -- the rest of postgres_tools.py's
    functions could be exposed the same way if this server were adopted
    as the primary tool path.
    """
    return [
        Tool(
            name="add_medicine",
            description="Add a new medicine for a user. Requires human approval upstream — this tool assumes approval already happened.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "name": {"type": "string"},
                    "strength": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["user_id", "name"],
            },
        ),
        Tool(
            name="schedule_appointment",
            description="Schedule a doctor appointment for a user. Requires human approval upstream.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "doctor_name": {"type": "string"},
                    "specialty": {"type": "string"},
                    "scheduled_for": {"type": "string", "format": "date-time"},
                    "notes": {"type": "string"},
                },
                "required": ["user_id", "doctor_name", "scheduled_for"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """MCP's execution endpoint: a client calls this with a tool name and
    arguments (matching one of the schemas declared in list_tools above),
    and this dispatches to the matching postgres_tools function -- opening
    its own DB session per call, since this server has no concept of a
    FastAPI request/response cycle to hang a session off of.
    """
    async with AsyncSessionLocal() as db:
        if name == "add_medicine":
            result = await postgres_tools.add_medicine(
                db, arguments["user_id"], arguments["name"],
                arguments.get("strength"), arguments.get("notes"),
            )
        elif name == "schedule_appointment":
            from datetime import datetime
            result = await postgres_tools.schedule_appointment(
                db, arguments["user_id"], arguments["doctor_name"],
                arguments.get("specialty"),
                datetime.fromisoformat(arguments["scheduled_for"]),
                arguments.get("notes"),
            )
        else:
            result = {"error": f"Unknown tool: {name}"}
    # MCP tool results are returned as a list of content blocks -- here,
    # a single text block containing the Python dict's string repr. A
    # production server would likely return structured JSON text instead.
    return [TextContent(type="text", text=str(result))]


async def main():
    """Entry point when run standalone (`python -m app.mcp_servers.mcp_stdio_server`).
    stdio_server() wires the MCP server's input/output to this process's
    actual stdin/stdout streams -- this is the same mechanism most local
    MCP servers use to talk to an MCP client (e.g. Claude Desktop, or a
    LangChain MultiServerMCPClient) running as its parent process.
    """
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
