<div align="center">
  <img src="https://img.shields.io/badge/Status-Production%20Ready-success.svg" alt="Status">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Market-India%20%26%20NRI-orange.svg" alt="Market">
  <h1>CarePilot AI 🧬</h1>
  <p><strong>Caregiving Intelligence System for Families with Aging Parents</strong></p>
  <p><em>CarePilot AI is not a medicine tracker. It watches over your parent in the background and speaks up only when something is actually wrong — like a smoke detector in the home.</em></p>
</div>

---

## 🎯 1. Product Overview

**CarePilot AI** is a background caregiving intelligence system designed specifically for adult children (Caregivers) caring for aging parents (Patients) living at home.

### 👥 The Two User Personas

1. **The Caregiver** (Primary Product User — signs up, owns account, receives alerts):
   - Adult child of the patient (typically aged 28–45), living with the parent or away in another city/country (NRI).
   - Busy working professional who carries ongoing low-grade anxiety about whether something is quietly going wrong with their parent's health.
   - Accesses CarePilot via the **Web Dashboard & Multi-Agent AI Chat**.

2. **The Patient** (The Parent — affected by the system, but NOT a traditional app user):
   - Aging parent (typically aged 60–80).
   - **Zero App Installation, Zero Login, Zero Typing.**
   - Receives a low-effort daily touchpoint over a channel they already use daily (**WhatsApp voice message**, text reply, or **fallback IVR phone call**). Total effort: ~15–20 seconds.

---

## 💡 2. The Problem & Value Proposition

### ❌ The Problem Stated Precisely
> *"Whether I live with my aging parent or far away, I cannot watch over their health continuously — I have a job, I sleep, I get distracted — and I have no reliable way to know if something is quietly going wrong until it's already a crisis."*

Physical distance makes anxiety worse, but it isn't the root cause — **the root cause is that continuous vigilance isn't something any single, busy human can sustain, present or not.** Passive medicine trackers fail because caregivers forget to log. Single missed doses aren't emergencies; a 3-week unnoticed adherence dip or an unwatched vitals trend is.

### ✨ What Value CarePilot AI Brings
- **Silence is a Feature**: Zero unnecessary notifications on normal days.
- **Actionable Pattern Alerts**: Plain-language alerts delivered only when longitudinal thresholds are breached (e.g. 3+ missed check-ins in 7 days, 2-day check-in gap, high BP trends).
- **Auto-Escalation Chain**: Unacknowledged alerts automatically escalate to a secondary designated family contact within a defined window.
- **Safe-by-Construction HITL**: No AI agent can write to a patient's medical record without explicit human approval.
- **India-Specific Value-Add**: Generic medicine substitute search (₹ INR savings), ABDM / ABHA Health ID linking, monthly spend tracking, and Tata 1mg / PharmEasy pharmacy refill HITL proposals.
- **Document OCR & Auto-Reconciliation**: Upload handwritten/printed prescriptions or lab PDFs; CarePilot extracts lab values into time-series charts and proposes missing medication updates for human approval.
- **One-Tap Emergency Mode**: Instantly dispatches alerts to all family caregivers, shares location, and displays a doctor-ready emergency summary.

---

## 🏗️ 3. Architecture & Tech Stack

CarePilot AI is built on a high-throughput, multi-agent **LangGraph** architecture backed by PostgreSQL with vector search and an asynchronous background pattern-watching engine.

```mermaid
graph TD
    subgraph Patient Touchpoint Loop
        PCall[WhatsApp Voice / IVR Phone Call] --> Speech2Text[Speech-to-Text Transcription]
        Speech2Text --> CheckinParser[LLM Check-in Parser Agent]
        CheckinParser --> AdherenceLog[(Medication Logs & Streaks)]
    end

    subgraph Background Pattern Watcher
        AdherenceLog --> PatternAgent[Longitudinal Intelligence Watcher]
        VitalsLog[(Vitals Logs)] --> PatternAgent
        PatternAgent -->|Anomaly Detected| AlertEngine[Alert & Auto-Escalation Engine]
        AlertEngine -->|Primary Timeout| SecondaryCaregiver[Escalate to Secondary Contact]
    end

    subgraph Caregiver Multi-Agent System
        UserPrompt[Caregiver Request] --> Guardrail[Input Guardrail Classifier]
        Guardrail -- Allowed --> Supervisor[Supervisor Router]
        Supervisor --> MedAgent[Medicine Agent]
        Supervisor --> DosAgent[Dosage Agent]
        Supervisor --> ApptAgent[Appointment Agent]
        Supervisor --> RecAgent[Records Agent / RAG Search]
        
        MedAgent & DosAgent & ApptAgent --> HITL[Human Approval Gate]
        HITL -->|Approved / Edited| DBExec[Database Write Tools]
        HITL -->|Rejected| Cancel[Action Cancelled]
    end
```

### 🛠️ Tech Stack & Architectural Decisions

| Layer | Technology | Decision Rationale |
| :--- | :--- | :--- |
| **Backend Framework** | **FastAPI (Python 3.13)** | High performance, native async/await for I/O operations, seamless pydantic validation, OpenAPI docs. |
| **Database & ORM** | **PostgreSQL + SQLAlchemy 2.0 + Asyncpg** | Relational integrity for user/patient scoping, ACID guarantees for medical records, fast async database driver. |
| **Vector Search** | **pgvector** | Embedded vector similarity search for medical PDF chunks directly inside Postgres without requiring an external vector DB. |
| **Multi-Agent Engine** | **LangGraph + LangChain** | State-graph architecture enforcing explicit node routing, checkpointer persistence across requests, and structural HITL interrupt/resume capabilities. |
| **LLM Inference** | **Groq API (Llama 3.3 70B & 3.1 8B)** | Ultra-low latency (<500ms response time) essential for real-time chat and high-precision structured JSON parsing. |
| **Document OCR & RAG** | **PyPDF + SentenceTransformers (`all-MiniLM-L6-v2`)** | Lightweight 384-dim semantic embedding model running locally for fast PDF indexing and search. |
| **Background Scheduler** | **APScheduler (AsyncIO)** | Asynchronous interval job scheduling for dosage checks, longitudinal pattern analysis, and alert escalations. |
| **Frontend UI** | **Vanilla HTML5 + Jinja2 + Modern CSS** | Zero JavaScript framework overhead, vibrant glassmorphic design system, responsive touchpoint UIs. |

---

## 🔄 4. End-to-End User Flow

1. **Onboarding & Patient Profile Setup**: Caregiver signs up -> creates Patient profile (e.g. "Ram Sharma", age 68, Hindi) -> sends one-time verification message to patient's phone.
2. **Daily Check-in Loop**: Scheduled time arrives -> Patient receives WhatsApp voice check-in -> Patient replies via voice note ("Haan, doctor ne bataya tha woh subah ki dawai le li") -> Check-in Parser Agent transcribes and converts to `taken` adherence status -> Supply count decrements, streak increments.
3. **Longitudinal Pattern Watching & Escalation**: Background pattern agent runs every 15 mins. If 3+ missed check-ins or high BP trend detected -> plain-language alert sent to Primary Caregiver. If unacknowledged within 15 mins -> automatically escalates to Secondary Caregiver.
4. **Document Upload & Auto-Reconciliation**: Caregiver uploads a prescription image/PDF -> OCR extracts text -> parses HbA1c & BP into Vitals charts -> detects new medicines -> drafts HITL proposal card in chat for approval.
5. **India Generic Medicine Savings**: System compares active prescriptions against generic substitute catalog (e.g. Telma 40mg vs Telmisartan 40mg) and displays ₹ INR monthly/annual savings.
6. **One-Tap Emergency Mode**: Caregiver taps Emergency SOS -> notifies all linked family members, shares location, and displays a doctor-ready emergency summary screen.

---

## 🌟 5. Complete Feature List

- [x] **Patient Entity & Scoping**: Multi-patient management per caregiver account with role-based permissions (`primary`, `secondary`, `viewer`).
- [x] **Patient Daily Check-in Engine**: Outbound WhatsApp voice/text and fallback IVR phone call touchpoints with LLM response parser.
- [x] **Longitudinal Pattern Intelligence**: Background watcher detecting 3+ missed check-ins, check-in gaps, vitals trends, polypharmacy, and adherence-vitals correlations.
- [x] **Auto-Escalation Chain**: Unacknowledged alerts automatically escalate to secondary family contacts.
- [x] **Structural HITL Approval Gate**: Topological guarantee that no agent can write to database records without human approval.
- [x] **Document Intelligence & OCR**: PDF/Image OCR, lab metric parser (HbA1c, BP, Glucose, Creatinine, Cholesterol), and prescription auto-reconciliation.
- [x] **India-Specific Value-Add**: Generic medicine substitute lookup, ₹ INR spend calculator, ABDM / ABHA Health ID verification, and pharmacy refill HITL proposals.
- [x] **Family Coordination**: Shared activity feed and care task manager between family caregivers.
- [x] **Device & Emergency Infrastructure**: Vitals sync, fall detection event simulator, and One-Tap Emergency SOS mode.
- [x] **Elderly-Friendly Web Touchpoint**: Large-text, 1-tap confirmation view at `/patient/touchpoint/{share_token}`.

---

## ⚡ 6. How to Setup and Run

### Prerequisites
- Python 3.10+ installed
- PostgreSQL 14+ with `pgvector` extension installed
- Groq API Key

### Step 1: Clone & Setup Virtual Environment
```bash
cd /Users/harsh/Desktop/healthcare-ai-system
python3 -m venv .venv3.13
source .venv3.13/bin/activate
pip install -r requirements.txt
```

### Step 2: Environment Configuration
Copy `.env.example` to `.env` and fill in your database and API credentials:
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/healthcare_ai
DATABASE_URL_SYNC=postgresql://postgres:postgres@localhost:5432/healthcare_ai
GROQ_API_KEY=your_groq_api_key_here
JWT_SECRET_KEY=supersecretjwtkey_carepilot_2026
```

### Step 3: Initialize Database & Vector Extension
```bash
python -m scripts.init_db --reset
```

### Step 4: Run Verification Tests
```bash
PYTHONPATH=. python /Users/harsh/.gemini/antigravity-ide/brain/c081d3cb-d804-4dce-8a66-27085688c26c/scratch/test_carepilot.py
```

### Step 5: Launch Server
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Open your browser at `http://127.0.0.1:8000` to start exploring CarePilot AI.

---

## 📜 License & Compliance
This software is provided for caregiving intelligence and health logistics support. It does not provide medical diagnosis or clinical treatment advice.
