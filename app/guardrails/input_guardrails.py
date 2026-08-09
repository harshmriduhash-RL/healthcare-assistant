"""
Input guardrails: the FIRST thing that touches a user's chat message,
before any LangGraph agent ever sees it. See app/api/chat.py's
start_chat() route, which calls run_input_guardrails() before invoking
the agent graph at all.

Two checks run here, deliberately cheap and mostly deterministic:

1. Prompt-injection / jailbreak heuristics -- a fast regex/keyword screen
   that catches obvious attempts to manipulate the system (e.g. "ignore
   your instructions"). This runs BEFORE any LLM call, so it can't itself
   be tricked by clever phrasing that would fool a model.

2. Scope + diagnosis check via a small, fast Groq model -- is this message
   even something this app should handle (medicine/dosage/records/
   appointment), or is it asking for a medical diagnosis or clinical
   advice, which this system is explicitly built to never provide?

Guardrails never call a write tool and never make the final routing
decision themselves -- they only decide whether the message is allowed
to reach the supervisor agent, and if so, tag it with a rough scope label
the supervisor can use as a routing hint (see app/agents/supervisor.py).
"""

import re
from dataclasses import dataclass

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app.core.config import settings

# Regex patterns that catch common prompt-injection phrasing. This is a
# simple denylist, not a comprehensive defense -- it's meant to catch
# obvious/lazy jailbreak attempts cheaply, with the LLM-based scope check
# below as a second layer for anything subtler.
INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior) instructions",
    r"you are now (in )?(developer|dan|jailbreak) mode",
    r"disregard (the )?system prompt",
    r"reveal your (system prompt|instructions)",
    r"act as if you have no (restrictions|guardrails|filters)",
]


@dataclass
class GuardrailResult:
    """The outcome of running guardrails on one message."""
    allowed: bool  # False means: stop here, don't call the agent graph at all
    reason: str  # shown to the user directly if allowed=False; "ok" if allowed=True
    scope: str | None = None  # medicine | dosage | records | appointment | general | out_of_scope -- a hint for the supervisor's routing


class ScopeClassification(BaseModel):
    """Structured output shape the guardrail LLM call is forced to return
    (via with_structured_output below) -- this is what makes the check
    reliable rather than having to parse free-text model output.
    """
    scope: str = Field(description="One of: medicine, dosage, records, appointment, general, out_of_scope")
    is_diagnosis_request: bool = Field(description="True if the user is asking for a medical diagnosis, "
                                                     "treatment recommendation, or interpretation of symptoms")
    reasoning: str


# A single shared ChatGroq client for the guardrail check, using the
# smallest/fastest configured model (see app/core/config.py's
# groq_model_guardrail) since this call runs on every single message
# and directly adds to the user's perceived latency. temperature=0 for
# consistent, repeatable classification rather than creative variation.
_guardrail_llm = ChatGroq(model=settings.groq_model_guardrail, api_key=settings.groq_api_key, temperature=0)


def _check_injection(text: str) -> bool:
    """Case-insensitive check of the message against every pattern in
    INJECTION_PATTERNS. Returns True (blocked) on the first match.
    """
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS)


async def run_input_guardrails(user_message: str) -> GuardrailResult:
    """The main entry point, called once per incoming chat message.

    Order of checks matters for both safety and cost: cheap, deterministic
    checks (injection regex, length) run first and can reject a message
    without ever calling the LLM at all. The LLM-based scope/diagnosis
    check only runs if those pass.
    """
    # Cheapest check first: does the raw text match a known injection pattern?
    if _check_injection(user_message):
        return GuardrailResult(allowed=False, reason="Message matched a prompt-injection pattern and was blocked.")

    if len(user_message.strip()) == 0:
        return GuardrailResult(allowed=False, reason="Empty message.")

    if len(user_message) > 4000:
        # Guards against extremely long messages that could be an attempt
        # to bury an injection deep in filler text, or just an accidental
        # paste -- either way, reject rather than pass it to an LLM.
        return GuardrailResult(allowed=False, reason="Message too long.")

    # with_structured_output forces the model's response to conform to the
    # ScopeClassification schema above (rather than free text we'd have to
    # parse ourselves), which makes this check both reliable and cheap to
    # act on programmatically.
    structured_llm = _guardrail_llm.with_structured_output(ScopeClassification)
    classification: ScopeClassification = await structured_llm.ainvoke([
        SystemMessage(content=(
            "Classify the user's message for a healthcare assistant app that manages "
            "medicines, dosages, medical record uploads, and doctor appointment scheduling. "
            "The app must NEVER provide a diagnosis or clinical advice — only administrative "
            "and record-keeping actions, always subject to human approval."
        )),
        HumanMessage(content=user_message),
    ])

    # This is the core safety rule for the whole app: no diagnosis, no
    # clinical advice, ever -- caught here before any agent gets a chance
    # to (accidentally or otherwise) answer a medical question it shouldn't.
    if classification.is_diagnosis_request:
        return GuardrailResult(
            allowed=False,
            reason=(
                "This assistant can't provide medical diagnoses or clinical advice. "
                "I can help you log symptoms in your records or schedule an appointment "
                "with your doctor instead."
            ),
            scope="out_of_scope",
        )

    if classification.scope == "out_of_scope":
        return GuardrailResult(
            allowed=False,
            reason="That request is outside what this assistant handles (medicines, dosages, records, appointments).",
            scope="out_of_scope",
        )

    # Passed everything -- allowed through to the supervisor, carrying the
    # classified scope along as a routing hint.
    return GuardrailResult(allowed=True, reason="ok", scope=classification.scope)
