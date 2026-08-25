"""
Input guardrails: message length, injection checks, and scope/diagnosis classification.
Includes fallback offline classification for zero-downtime performance.
"""

import re
from dataclasses import dataclass

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app.core.config import settings

INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior) instructions",
    r"you are now (in )?(developer|dan|jailbreak) mode",
    r"disregard (the )?system prompt",
    r"reveal your (system prompt|instructions)",
    r"act as if you have no (restrictions|guardrails|filters)",
]


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str
    scope: str | None = None


class ScopeClassification(BaseModel):
    scope: str = Field(description="One of: medicine, dosage, records, appointment, general, out_of_scope")
    is_diagnosis_request: bool = Field(description="True if asking for medical diagnosis/treatment advice")
    reasoning: str


def _check_injection(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS)


def _fallback_classify(user_message: str) -> GuardrailResult:
    """Fallback classifier when Groq API key is unconfigured or unreachable."""
    msg = user_message.lower()

    # Diagnosis check
    diag_keywords = ["do i have", "am i sick", "what disease", "diagnose me", "treatment for my", "symptom check"]
    if any(k in msg for k in diag_keywords):
        return GuardrailResult(
            allowed=False,
            reason="This assistant cannot provide medical diagnoses or clinical advice. Please consult a qualified doctor.",
            scope="out_of_scope"
        )

    if any(k in msg for k in ["dosage", "twice daily", "morning", "evening", "take 5mg", "take 500mg"]):
        scope = "dosage"
    elif any(k in msg for k in ["medicine", "med", "pill", "drug", "metformin", "amlodipine", "aspirin", "add"]):
        scope = "medicine"
    elif any(k in msg for k in ["appointment", "doctor", "schedule", "book", "clinic"]):
        scope = "appointment"
    elif any(k in msg for k in ["record", "pdf", "lab", "test", "report", "blood", "cholesterol", "hba1c"]):
        scope = "records"
    else:
        scope = "general"

    return GuardrailResult(allowed=True, reason="ok", scope=scope)


async def run_input_guardrails(user_message: str) -> GuardrailResult:
    if _check_injection(user_message):
        return GuardrailResult(allowed=False, reason="Message matched a prompt-injection pattern and was blocked.")

    if len(user_message.strip()) == 0:
        return GuardrailResult(allowed=False, reason="Empty message.")

    if len(user_message) > 4000:
        return GuardrailResult(allowed=False, reason="Message too long.")

    try:
        llm = ChatGroq(model=settings.groq_model_guardrail, api_key=settings.groq_api_key, temperature=0)
        structured_llm = llm.with_structured_output(ScopeClassification)
        classification: ScopeClassification = await structured_llm.ainvoke([
            SystemMessage(content=(
                "Classify the user's message for a healthcare assistant app managing "
                "medicines, dosages, medical records, and appointments. "
                "NEVER provide medical diagnosis or clinical advice."
            )),
            HumanMessage(content=user_message),
        ])

        if classification.is_diagnosis_request:
            return GuardrailResult(
                allowed=False,
                reason="This assistant cannot provide medical diagnoses or clinical advice.",
                scope="out_of_scope",
            )

        if classification.scope == "out_of_scope":
            return GuardrailResult(
                allowed=False,
                reason="That request is outside what this assistant handles (medicines, dosages, records, appointments).",
                scope="out_of_scope",
            )

        return GuardrailResult(allowed=True, reason="ok", scope=classification.scope)
    except Exception:
        # Fallback to deterministic classifier on API errors or missing keys
        return _fallback_classify(user_message)
