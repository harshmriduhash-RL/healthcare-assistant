"""
The system's observability/audit layer.

Every meaningful step an agent takes -- a guardrail check, a routing
decision, a proposed action, a human's approve/reject/edit decision, or
an actual database write -- gets logged as a row in the `agent_audit_log`
table via the helpers below. This is what powers the "View trace" button
in the chat UI (see the /api/chat/trace/{thread_id} route in
app/api/chat.py): it's just reading these rows back out, grouped by
conversation thread, in order.

This is deliberately simple (a Postgres table, not a dedicated tracing
system like LangSmith or OpenTelemetry) -- for a prototype demo it's more
important that the trace is easy to explain and query than that it's
production-grade observability infrastructure.
"""

import time
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentAuditLog


async def log_agent_event(
    db: AsyncSession, user_id: str, thread_id: str, agent_name: str,
    action_type: str, payload: dict | None = None, latency_ms: int | None = None,
) -> None:
    """Write a single audit log row and commit immediately.

    Called directly (not via the `traced` context manager below) in places
    where we already know the latency up front or don't need to measure it,
    e.g. logging a guardrail's pass/fail decision.
    """
    entry = AgentAuditLog(
        user_id=user_id, thread_id=thread_id, agent_name=agent_name,
        action_type=action_type, payload=payload, latency_ms=latency_ms,
    )
    db.add(entry)
    await db.commit()


@asynccontextmanager
async def traced(db: AsyncSession, user_id: str, thread_id: str, agent_name: str, action_type: str, payload: dict | None = None):
    """Context-manager version: wrap a block of code and automatically log
    how long it took, once it finishes (successfully or not).

    Usage:
        async with traced(db, user.id, thread_id, "medicine_agent", "propose"):
            ... do the work ...
    On exit, this computes elapsed wall-clock time in milliseconds and logs
    it via log_agent_event -- so callers don't have to manually start/stop
    a timer around every traced block.
    """
    start = time.perf_counter()  # monotonic clock, safe for measuring durations
    try:
        yield
    finally:
        # This runs whether the block succeeded or raised an exception,
        # so we always get a latency measurement even on failure paths.
        latency_ms = int((time.perf_counter() - start) * 1000)
        await log_agent_event(db, user_id, thread_id, agent_name, action_type, payload, latency_ms)
