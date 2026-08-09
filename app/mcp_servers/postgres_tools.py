"""
The MCP-style tool layer: the small, explicit set of functions that are
actually allowed to write to medicines, dosages, and appointments in the
database.

This module plays the role of an MCP (Model Context Protocol) server's
tool implementations -- a clean, narrow boundary between "what an agent
can ask for" and "what code actually touches the database." In this
prototype these functions are called directly (in-process, for lower
demo latency) from app/agents/graph.py's execute_action_node. The same
operations are ALSO wrapped as real MCP tools, reachable over the actual
MCP protocol, in mcp_stdio_server.py in this same directory -- so the
tool/agent decoupling here is genuine, not just a naming convention.

CRITICAL: every function in this file is only ever called AFTER a human
has approved the corresponding action. See app/agents/hitl.py (the
approval gate) and app/agents/graph.py (execute_action_node, the only
caller of these functions). Nothing else in the codebase calls these
directly except app/api/dashboard.py's direct-edit routes, which are a
DIFFERENT, deliberately non-agent path (see the README, section 4, for
why direct dashboard edits don't need HITL).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Dosage, Medicine


async def add_medicine(db: AsyncSession, user_id: str, name: str, strength: str | None, notes: str | None) -> dict:
    """Insert a new Medicine row for this user and return its key fields."""
    med = Medicine(user_id=user_id, name=name, strength=strength, notes=notes)
    db.add(med)
    await db.commit()
    await db.refresh(med)  # reload the row's DB-generated fields (e.g. created_at) after commit
    return {"id": med.id, "name": med.name, "strength": med.strength}


async def update_medicine(db: AsyncSession, user_id: str, medicine_id: str, **fields) -> dict:
    """Update an existing medicine's fields, but ONLY if it belongs to this
    user (the WHERE clause below double-checks ownership even though the
    caller should already have verified it) -- defense in depth against a
    bug elsewhere accidentally passing the wrong medicine_id.
    """
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.user_id == user_id))
    med = result.scalar_one_or_none()
    if not med:
        return {"error": "Medicine not found"}
    # Only overwrite fields that were actually passed with a non-None
    # value -- so e.g. calling update_medicine(strength="10mg") doesn't
    # accidentally wipe out the existing name/notes.
    for key, value in fields.items():
        if hasattr(med, key) and value is not None:
            setattr(med, key, value)
    await db.commit()
    return {"id": med.id, "name": med.name, "updated": True}


async def remove_medicine(db: AsyncSession, user_id: str, medicine_id: str) -> dict:
    """Hard-delete a medicine (and, via the cascade defined in
    app/db/models.py, all of its dosages too).
    """
    result = await db.execute(select(Medicine).where(Medicine.id == medicine_id, Medicine.user_id == user_id))
    med = result.scalar_one_or_none()
    if not med:
        return {"error": "Medicine not found"}
    await db.delete(med)
    await db.commit()
    return {"deleted": True, "id": medicine_id}


async def add_dosage(db: AsyncSession, medicine_id: str, amount: str, frequency: str, time_of_day: str | None) -> dict:
    """Insert a new Dosage row linked to an existing medicine."""
    dosage = Dosage(medicine_id=medicine_id, amount=amount, frequency=frequency, time_of_day=time_of_day)
    db.add(dosage)
    await db.commit()
    await db.refresh(dosage)
    return {"id": dosage.id, "amount": dosage.amount, "frequency": dosage.frequency}


async def update_dosage(db: AsyncSession, dosage_id: str, **fields) -> dict:
    """Update an existing dosage's fields. Note: unlike update_medicine,
    this doesn't re-verify user ownership via a join -- the caller
    (execute_action_node) is trusted to have already resolved the correct
    dosage_id for this user's own data through the conversation.
    """
    result = await db.execute(select(Dosage).where(Dosage.id == dosage_id))
    dosage = result.scalar_one_or_none()
    if not dosage:
        return {"error": "Dosage not found"}
    for key, value in fields.items():
        if hasattr(dosage, key) and value is not None:
            setattr(dosage, key, value)
    await db.commit()
    return {"id": dosage.id, "updated": True}


async def remove_dosage(db: AsyncSession, dosage_id: str) -> dict:
    """Hard-delete a single dosage entry (does not touch its parent medicine)."""
    result = await db.execute(select(Dosage).where(Dosage.id == dosage_id))
    dosage = result.scalar_one_or_none()
    if not dosage:
        return {"error": "Dosage not found"}
    await db.delete(dosage)
    await db.commit()
    return {"deleted": True, "id": dosage_id}


async def schedule_appointment(
    db: AsyncSession, user_id: str, doctor_name: str, specialty: str | None,
    scheduled_for: datetime, notes: str | None,
) -> dict:
    """Insert a new Appointment row, already marked "confirmed" -- by the
    time this function runs, a human has already approved it via the HITL
    gate, so there's no need for a separate "proposed" intermediate state
    in the database (that intermediate state lives in LangGraph's
    checkpointed AgentState instead, before approval).
    """
    appt = Appointment(
        user_id=user_id, doctor_name=doctor_name, specialty=specialty,
        scheduled_for=scheduled_for, notes=notes, status="confirmed",
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    return {"id": appt.id, "doctor_name": appt.doctor_name, "scheduled_for": appt.scheduled_for.isoformat()}
