"""
Pydantic request/response models for the API layer.

FastAPI uses these to: (1) validate incoming JSON before a route's code
ever runs -- e.g. a signup request missing a password gets auto-rejected
with a 422 before hitting our logic, and (2) auto-generate the OpenAPI
docs at /docs. Keeping all of them in one file makes it easy to see every
shape of data the API accepts at a glance.
"""

from pydantic import BaseModel, Field


# ---------- Auth ----------
# Deliberately minimal: username + password only. No email, no OTP, no
# third-party auth -- keeping signup/login as simple as possible was an
# explicit product decision.

class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str  # plaintext here (over HTTPS in production) -- hashed immediately in app/api/auth.py, never stored as-is


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------- Chat / agent orchestration ----------

class ChatRequest(BaseModel):
    message: str
    # None on the very first message of a conversation -- app/api/chat.py
    # generates a new UUID for it. Sent back on every subsequent message
    # so the LangGraph checkpointer can resume the same conversation state.
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    """Sent when the human responds to a pending approval card in the chat UI."""
    thread_id: str  # which paused conversation this decision applies to
    decision: str  # one of: "approved" | "rejected" | "edited"
    feedback: str | None = None  # optional human-readable reason (mainly for rejections)
    edited_payload: dict | None = None  # only populated when decision == "edited" -- replaces the agent's original proposed values


# --- Direct dashboard CRUD (user editing their own data directly, no agent involved) ---
# These are intentionally separate, simpler models from the agent-proposed-action
# payloads above: a dashboard edit is a straightforward "here are the new field
# values," not something an LLM needs to reason about or propose.

class MedicineCreate(BaseModel):
    name: str
    strength: str | None = None  # e.g. "500mg" -- free text, not a structured unit
    notes: str | None = None
    supply_count: int | None = None
    refill_threshold: int | None = None


class MedicineUpdate(BaseModel):
    # All fields optional: a PUT request only needs to send the fields it's
    # actually changing. See MedicineUpdate.model_dump(exclude_unset=True)
    # usage in app/api/dashboard.py -- fields the client didn't send are
    # left untouched on the existing row rather than being overwritten with None.
    name: str | None = None
    strength: str | None = None
    notes: str | None = None
    supply_count: int | None = None
    refill_threshold: int | None = None


class DosageCreate(BaseModel):
    medicine_id: str  # which medicine this dosage schedule belongs to
    amount: str  # e.g. "5mg", "1 tablet" -- kept as free text for flexibility
    frequency: str  # e.g. "daily", "twice a day"
    time_of_day: str | None = None  # comma-separated 24h times, e.g. "08:00,20:00"
    consumption_instructions: str | None = None


class DosageUpdate(BaseModel):
    amount: str | None = None
    frequency: str | None = None
    time_of_day: str | None = None
    consumption_instructions: str | None = None


class RecordUpdate(BaseModel):
    record_type: str | None = None  # e.g. "lab_report", "prescription", "imaging"
    filename: str | None = None
