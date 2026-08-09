# Healthcare Multi-Agent AI System

A working prototype of an AI-native healthcare assistant: a team of specialized AI agents
that manage a person's medicines, dosage schedules, medical record history, and doctor
appointments — with a hard rule baked into the architecture, not just the prompts: **no
agent can write anything to the database until a human explicitly approves it.**

This document is written so that someone who has never seen the code can understand what
the product does, why it's built the way it is, and how to walk through it end-to-end.

## Quick Start

1. Install dependencies and create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Copy and configure the environment file:
   ```bash
   cp .env.example .env
   # then fill in DATABASE_URL, DATABASE_URL_SYNC, GROQ_API_KEY, JWT_SECRET_KEY
   ```
3. Create the PostgreSQL database and run migrations:
   ```bash
   createdb healthcare_ai
   alembic upgrade head
   ```
4. Start the app locally:
   ```bash
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
5. Open `http://127.0.0.1:8000` in your browser.


---

## 1. What problem this solves

Most "AI health assistant" demos are a chatbot wrapped around an LLM that answers questions.
That's not what this is. This system is closer to a **junior clinical administrator that
never acts alone** — it can understand a request in plain English, figure out exactly what
change needs to be made, and prepare that change for you — but it physically cannot commit
that change to your health record without you clicking "Approve." That constraint is the
entire point of the project: it's a demonstration of how to build multi-agent AI systems
that are *safe by construction* in a domain (healthcare) where an AI silently taking the
wrong action is unacceptable.

## 2. Who it's for / use cases

- **A patient managing chronic medication** — "I started taking my blood pressure medicine
  again, can you log it?" -> the assistant proposes adding it, you approve, it's saved.
- **Someone juggling multiple prescriptions with different schedules** — dosages have their
  own times-of-day, and a background job reminds the user when one is due.
- **A patient who wants their medical history searchable** — upload lab reports and
  prescriptions as PDFs; later ask "what was my cholesterol last time?" and get an answer
  grounded in the actual uploaded documents, not the model's general knowledge.
- **Booking a follow-up appointment** — but only when the user actually asks for it or says
  it's okay; the assistant is deliberately built to never assume consent to schedule.
- **An organization that needs an auditable AI system** — every guardrail check, every
  routing decision, every proposed action, every human decision, and every executed write is
  logged with a timestamp and latency, viewable per conversation via "View trace."

## 3. What's built vs. explicitly out of scope

| Area | Status |
|---|---|
| Multi-user accounts with authentication | Built (username + password only, by design) |
| Add / edit / delete medicines | Built (via chat AND direct dashboard forms) |
| Add / edit / delete dosage schedules | Built (via chat AND direct dashboard forms) |
| Upload / edit / delete medical record PDFs | Built (dashboard) |
| Extracting text from PDFs + semantic search over them | Built |
| Human-in-the-loop approval on every agent-proposed write | Built, structurally enforced |
| Doctor appointment scheduling (only with explicit permission) | Built (chat only, always HITL-gated) |
| Background reminders (dosage due / appointment upcoming) | Built |
| Medical diagnosis or clinical advice | Deliberately excluded — the guardrail layer blocks and redirects this |
| Real calendar/EHR integration | Out of scope for this prototype — appointments are stored locally |
| Role-based access control / clinician-facing views | Out of scope — single-role patient accounts only |

---

## 4. How it works — the architecture

```
Browser (Jinja2 + vanilla JS)
        |
        v
FastAPI routes  --------------------------------------------------------+
        |                                                                |
        v                                                                |
Input Guardrails  (app/guardrails/input_guardrails.py)                   |
  - blocks prompt-injection attempts                                     |
  - blocks requests for diagnosis/clinical advice                        |
  - classifies the message's rough scope (medicine/dosage/records/       |
    appointment/general) to help the supervisor route it                 |
        | (only reaches here if allowed)                                 |
        v                                                                |
Supervisor Agent  (app/agents/supervisor.py)                             |
  - a LangGraph node that decides which ONE worker agent should          |
    handle this turn of conversation                                    |
        |                                                                |
        +--------------+--------------+--------------+                  |
        v              v              v              v                  |
   Medicine        Dosage       Appointment      Records/RAG             |
    Agent           Agent          Agent           Agent                 |
  (proposes)     (proposes)     (proposes)      (read-only --            |
        |              |              |           answers from           |
        +------+-------+------+-------+         uploaded PDFs,           |
               v              v                  no approval needed)     |
        Human-in-the-Loop Gate  (app/agents/hitl.py)                     |
          - the ONLY node allowed to hand off to a write tool            |
          - pauses the whole agent run here (LangGraph interrupt())      |
          - the frontend renders this as an "approval card"              |
          - the run resumes only when the human clicks                  |
            Approve / Reject / Save & Approve (edited)                   |
               |                                                         |
       +-------+--------+                                                |
       v                v                                                |
  execute_action   rejected_end                                          |
  (writes to DB     (ends the turn,                                      |
   via MCP tools)    nothing written)                                    |
       |                                                                  |
       v                                                                  |
  Postgres  (medicines, dosages, medical_records, record_chunks with     |
             pgvector embeddings, appointments, notifications,            |
             agent_audit_log)  <----------------------------------------- +
       ^
       |
Background Scheduler (app/core/scheduler.py, APScheduler)
  - runs independently of the agent graph
  - checks for due dosages / upcoming appointments on a timer
  - only ever WRITES notification rows -- never touches medicines,
    dosages, or appointments directly, and never talks to the agents
```

**Why this shape, specifically:**

- **Supervisor + worker agents, not one big prompt.** Each worker agent has one job (medicine
  changes, dosage changes, appointment scheduling, or read-only record search) and its own
  focused system prompt. The supervisor's only job is routing. This is what "multi-agent"
  means here — it's not marketing, the graph genuinely branches to different specialized
  agents based on what's being asked.

- **MCP-style tool boundary.** Database writes don't happen inline inside agent code — they go
  through a small, explicit set of tool functions in `app/mcp_servers/postgres_tools.py`, and
  there's a real MCP server variant (`app/mcp_servers/mcp_stdio_server.py`) that exposes the
  same operations over the actual Model Context Protocol. This keeps "what the agent can ask
  for" and "what the agent can execute" cleanly separated.

- **Human-in-the-loop is structural, not a suggestion in a prompt.** Look at
  `app/agents/graph.py`: the graph's edges are wired so that `execute_action` (the only node
  that calls a write tool) can only be reached from `human_approval` after it records
  `approved` or `edited`. A worker agent has no edge that skips this gate. An LLM going rogue
  or ignoring its instructions cannot bypass this — the graph topology itself prevents it.

- **Guardrails run before the supervisor, not after.** Prompt-injection attempts and requests
  for medical diagnosis are screened out before any agent even sees the message, so a
  jailbreak attempt never gets the chance to manipulate a downstream agent.

- **Direct dashboard edits are intentionally NOT HITL-gated.** When a user edits their own
  medicine list directly on `/dashboard` (not through chat), there's no agent proposing
  anything on their behalf — the human is already the one making the decision. HITL exists to
  govern *agent* actions specifically. Appointment scheduling has no direct-edit path for this
  reason — "schedule if asked or given permission" is exactly the kind of judgment call the
  agent+approval flow exists for.

## 5. The user flow, end to end

1. **Sign up / log in** (`/signup`, `/login`) — username + password, JWT stored in an httpOnly
   cookie. Every subsequent request is scoped to that user's own data only.

2. **Land on `/dashboard`** — see medicines (with their dosages nested underneath),
   upcoming appointments, and uploaded medical records, all at a glance. Direct add/edit/
   delete controls are available here for medicines, dosages, and record metadata.

3. **Upload a medical record PDF** — dropped into `/api/records/upload`, saved to disk,
   text extracted, chunked, embedded, and stored in Postgres via `pgvector` for later
   semantic search. This happens synchronously on upload — the record is searchable
   immediately.

4. **Go to `/chat`** to talk to the assistant instead of clicking through the dashboard —
   this is where the multi-agent system actually runs:
   - Type a request, e.g. "Add my metformin 500mg."
   - It passes through the guardrail check.
   - The supervisor routes it to the Medicine Agent.
   - The Medicine Agent decides this means `add_medicine` and proposes it.
   - Execution pauses. An **approval card** appears in the chat with the proposed action
     and its structured payload.
   - You can **Approve**, **Reject**, or click **Edit** to change the values inline before
     approving (e.g. fix a misheard dosage amount).
   - Only after Approve/edited-Approve does the write actually happen — visible immediately
     afterward on `/dashboard`.

5. **Ask a question about your records** — e.g. "What did my last blood panel say about
   cholesterol?" routes to the Records Agent, which does a similarity search over your
   uploaded PDFs' embedded chunks and answers using only what it retrieves — no approval
   step, because nothing is being written.

6. **Try to schedule an appointment** — the Appointment Agent will only propose one if you
   explicitly asked or clearly gave permission in the conversation; otherwise it declines to
   act, by design.

7. **Try a diagnosis-shaped question** — e.g. "What's wrong with me, I have chest pain?" —
   the input guardrail blocks this before it reaches any agent, and tells you plainly that
   this system doesn't give medical advice.

8. **Check "View trace"** on any chat turn — pulls the full audit log for that
   conversation thread: every guardrail check, routing decision, proposal, human decision,
   and execution, each with a latency in milliseconds.

9. **Reminders** — a background scheduler independently checks for dosages due and
   appointments coming up in the next 24 hours, surfacing them via the bell icon on
   `/dashboard` with an unread badge.

## 6. Feature list (detailed)

- **Auth**: username + password only (no email verification, OTP, or third-party auth — kept
  deliberately simple), bcrypt-hashed passwords, JWT in httpOnly cookies, all API
  routes protected by a `get_current_user` dependency.
- **Multi-tenant data isolation**: every table (`medicines`, `dosages`, `medical_records`,
  `appointments`, `notifications`, `agent_audit_log`) is scoped by `user_id`; every query
  filters on it.
- **Medicines & dosages CRUD**: reachable two ways — through the AI assistant (proposed,
  HITL-approved) or directly on the dashboard (immediate, since it's the user acting on
  their own data).
- **Medical records**: upload, list, edit metadata (record type), delete (cascades to
  the record's indexed chunks and removes the file from disk).
- **PDF text extraction + semantic search**: `pypdf` for extraction, chunked into ~800-char
  windows with overlap, embedded with `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim),
  stored and queried via `pgvector`'s cosine-distance index.
- **Guardrails**: regex-based prompt-injection screen (fast, deterministic) + an LLM-based
  scope/diagnosis classifier (`app/guardrails/input_guardrails.py`) using a small, fast Groq
  model so the check doesn't add noticeable latency.
- **Human-in-the-loop**: `interrupt()`/`Command(resume=...)` from LangGraph, backed by a
  Postgres checkpointer, so an approval can be given in a later, separate HTTP request (the
  graph run genuinely pauses, not just visually).
- **Observability**: every meaningful hop writes a row to `agent_audit_log` — guardrail
  checks, routing decisions, proposals, human decisions, and executions, each with latency.
- **Automation**: APScheduler background jobs for dosage-due and appointment-upcoming
  reminders, deliberately kept outside the agent/HITL system (see Section 4).

## 7. Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI | async-native, plays well with LangGraph's async execution |
| Frontend | Jinja2 + vanilla HTML/CSS/JS | no build step, easy to read and demo live |
| Agent orchestration | LangGraph | the `interrupt()`/checkpointer pattern is exactly built for HITL workflows |
| LLM calls | LangChain + `langchain-groq` | structured output (`with_structured_output`) for reliable agent decisions |
| Inference | Groq | fast enough that a supervisor -> worker -> HITL round trip still feels responsive live |
| Database | PostgreSQL + `pgvector` | one database for relational data AND vector search — no separate vector DB to run |
| Migrations | Alembic | versioned schema changes instead of a single destructive `create_all` |
| Tool boundary | MCP (Model Context Protocol) | genuine tool/agent decoupling, not just a naming convention |
| Automation | APScheduler | in-process, no extra service to run for a prototype |

## 8. Project layout

```
app/
  agents/          LangGraph state schema, supervisor, worker agents, HITL gate, RAG
    state.py         shared graph state (messages, proposed action, approval decision, etc.)
    supervisor.py     routes each turn to exactly one worker agent
    workers.py        medicine / dosage / appointment / records agents
    hitl.py           the human-approval interrupt node -- the system's core safety mechanism
    graph.py          wires all nodes/edges together and compiles the graph with a checkpointer
    rag.py            PDF extraction, chunking, embedding, semantic search
  api/             FastAPI routers
    auth.py           signup / login / logout
    chat.py           starts and resumes agent runs; the HITL request/response cycle
    dashboard.py      direct CRUD for medicines/dosages/records (not agent-mediated)
    records.py        PDF upload + listing
    notifications.py  list/mark-read for scheduler-generated reminders
    pages.py          serves the Jinja2 HTML pages
  core/            cross-cutting concerns
    config.py         all environment-driven settings in one place
    security.py       password hashing + JWT encode/decode
    deps.py           the get_current_user FastAPI dependency
    schemas.py        Pydantic request/response models
    observability.py  writes rows to the audit log
    scheduler.py       APScheduler background jobs (dosage/appointment reminders)
  guardrails/
    input_guardrails.py   prompt-injection screen + scope/diagnosis classifier
  mcp_servers/
    postgres_tools.py     the actual write functions (add/update/remove medicine, etc.)
    mcp_stdio_server.py   the same operations exposed as a real MCP server over stdio
  db/
    models.py         SQLAlchemy ORM models -- the entire schema
    session.py         async engine/session setup
  templates/        Jinja2 pages: login, signup, dashboard, chat
  static/css/        shared stylesheet
migrations/         Alembic environment + versioned migration files
scripts/init_db.py   quick one-shot schema creation (fallback to Alembic)

## 9. How it works — the architecture

```
Browser (Jinja2 + vanilla JS)
        |
        v
FastAPI routes  --------------------------------------------------------+
        |                                                                |
        v                                                                |
Input Guardrails  (app/guardrails/input_guardrails.py)                   |
  - blocks prompt-injection attempts                                     |
  - blocks requests for diagnosis/clinical advice                        |
  - classifies the message's rough scope (medicine/dosage/records/       |
    appointment/general) to help the supervisor route it                 |
        | (only reaches here if allowed)                                 |
        v                                                                |
Supervisor Agent  (app/agents/supervisor.py)                             |
  - a LangGraph node that decides which ONE worker agent should          |
    handle this turn of conversation                                    |
        |                                                                |
        +--------------+--------------+--------------+                  |
        v              v              v              v                  |
   Medicine        Dosage       Appointment      Records/RAG             |
    Agent           Agent          Agent           Agent                 |
  (proposes)     (proposes)     (proposes)      (read-only --            |
        |              |              |           answers from           |
        +------+-------+------+-------+         uploaded PDFs,           |
               v              v                  no approval needed)     |
        Human-in-the-Loop Gate  (app/agents/hitl.py)                     |
          - the ONLY node allowed to hand off to a write tool            |
          - pauses the whole agent run here (LangGraph interrupt())      |
          - the frontend renders this as an "approval card"              |
          - the run resumes only when the human clicks                  |
            Approve / Reject / Save & Approve (edited)                   |
               |                                                         |
       +-------+--------+                                                |
       v                v                                                |
  execute_action   rejected_end                                          |
  (writes to DB     (ends the turn,                                      |
   via MCP tools)    nothing written)                                    |
       |                                                                  |
       v                                                                  |
  Postgres  (medicines, dosages, medical_records, record_chunks with     |
             pgvector embeddings, appointments, notifications,            |
             agent_audit_log)  <----------------------------------------- +
       ^
       |
Background Scheduler (app/core/scheduler.py, APScheduler)
  - runs independently of the agent graph
  - checks for due dosages / upcoming appointments on a timer
  - only ever WRITES notification rows -- never touches medicines,
    dosages, or appointments directly, and never talks to the agents
```

**Why this shape, specifically:**

- **Supervisor + worker agents, not one big prompt.** Each worker agent has one job (medicine
  changes, dosage changes, appointment scheduling, or read-only record search) and its own
  focused system prompt. The supervisor's only job is routing. This is what "multi-agent"
  means here — it's not marketing, the graph genuinely branches to different specialized
  agents based on what's being asked.

- **MCP-style tool boundary.** Database writes don't happen inline inside agent code — they go
  through a small, explicit set of tool functions in `app/mcp_servers/postgres_tools.py`, and
  there's a real MCP server variant (`app/mcp_servers/mcp_stdio_server.py`) that exposes the
  same operations over the actual Model Context Protocol. This keeps "what the agent can ask
  for" and "what the agent can execute" cleanly separated.

- **Human-in-the-loop is structural, not a suggestion in a prompt.** Look at
  `app/agents/graph.py`: the graph's edges are wired so that `execute_action` (the only node
  that calls a write tool) can only be reached from `human_approval` after it records
  `approved` or `edited`. A worker agent has no edge that skips this gate. An LLM going rogue
  or ignoring its instructions cannot bypass this — the graph topology itself prevents it.

- **Guardrails run before the supervisor, not after.** Prompt-injection attempts and requests
  for medical diagnosis are screened out before any agent even sees the message, so a
  jailbreak attempt never gets the chance to manipulate a downstream agent.

- **Direct dashboard edits are intentionally NOT HITL-gated.** When a user edits their own
  medicine list directly on `/dashboard` (not through chat), there's no agent proposing
  anything on their behalf — the human is already the one making the decision. HITL exists to
  govern *agent* actions specifically. Appointment scheduling has no direct-edit path for this
  reason — "schedule if asked or given permission" is exactly the kind of judgment call the
  agent+approval flow exists for.

## 10. The user flow, end to end

1. **Sign up / log in** (`/signup`, `/login`) — username + password, JWT stored in an httpOnly
   cookie. Every subsequent request is scoped to that user's own data only.

2. **Land on `/dashboard`** — see medicines (with their dosages nested underneath),
   upcoming appointments, and uploaded medical records, all at a glance. Direct add/edit/
   delete controls are available here for medicines, dosages, and record metadata.

3. **Upload a medical record PDF** — dropped into `/api/records/upload`, saved to disk,
   text extracted, chunked, embedded, and stored in Postgres via `pgvector` for later
   semantic search. This happens synchronously on upload — the record is searchable
   immediately.

4. **Go to `/chat`** to talk to the assistant instead of clicking through the dashboard —
   this is where the multi-agent system actually runs:
   - Type a request, e.g. "Add my metformin 500mg."
   - It passes through the guardrail check.
   - The supervisor routes it to the Medicine Agent.
   - The Medicine Agent decides this means `add_medicine` and proposes it.
   - Execution pauses. An **approval card** appears in the chat with the proposed action
     and its structured payload.
   - You can **Approve**, **Reject**, or click **Edit** to change the values inline before
     approving (e.g. fix a misheard dosage amount).
   - Only after Approve/edited-Approve does the write actually happen — visible immediately
     afterward on `/dashboard`.

5. **Ask a question about your records** — e.g. "What did my last blood panel say about
   cholesterol?" routes to the Records Agent, which does a similarity search over your
   uploaded PDFs' embedded chunks and answers using only what it retrieves — no approval
   step, because nothing is being written.

6. **Try to schedule an appointment** — the Appointment Agent will only propose one if you
   explicitly asked or clearly gave permission in the conversation; otherwise it declines to
   act, by design.

7. **Try a diagnosis-shaped question** — e.g. "What's wrong with me, I have chest pain?" —
   the input guardrail blocks this before it reaches any agent, and tells you plainly that
   this system doesn't give medical advice.

8. **Check "View trace"** on any chat turn — pulls the full audit log for that
   conversation thread: every guardrail check, routing decision, proposal, human decision,
   and execution, each with a latency in milliseconds.

9. **Reminders** — a background scheduler independently checks for dosages due and
   appointments coming up in the next 24 hours, surfacing them via the bell icon on
   `/dashboard` with an unread badge.

## 11. Feature list (detailed)

- **Auth**: username + password only (no email verification, OTP, or third-party auth — kept
  deliberately simple), bcrypt-hashed passwords, JWT in httpOnly cookies, all API
  routes protected by a `get_current_user` dependency.
- **Multi-tenant data isolation**: every table (`medicines`, `dosages`, `medical_records`,
  `appointments`, `notifications`, `agent_audit_log`) is scoped by `user_id`; every query
  filters on it.
- **Medicines & dosages CRUD**: reachable two ways — through the AI assistant (proposed,
  HITL-approved) or directly on the dashboard (immediate, since it's the user acting on
  their own data).
- **Medical records**: upload, list, edit metadata (record type), delete (cascades to
  the record's indexed chunks and removes the file from disk).
- **PDF text extraction + semantic search**: `pypdf` for extraction, chunked into ~800-char
  windows with overlap, embedded with `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim),
  stored and queried via `pgvector`'s cosine-distance index.
- **Guardrails**: regex-based prompt-injection screen (fast, deterministic) + an LLM-based
  scope/diagnosis classifier (`app/guardrails/input_guardrails.py`) using a small, fast Groq
  model so the check doesn't add noticeable latency.
- **Human-in-the-loop**: `interrupt()`/`Command(resume=...)` from LangGraph, backed by a
  Postgres checkpointer, so an approval can be given in a later, separate HTTP request (the
  graph run genuinely pauses, not just visually).
- **Observability**: every meaningful hop writes a row to `agent_audit_log` — guardrail
  checks, routing decisions, proposals, human decisions, and executions, each with latency.
- **Automation**: APScheduler background jobs for dosage-due and appointment-upcoming
  reminders, deliberately kept outside the agent/HITL system (see Section 4).

## 12. Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI | async-native, plays well with LangGraph's async execution |
| Frontend | Jinja2 + vanilla HTML/CSS/JS | no build step, easy to read and demo live |
| Agent orchestration | LangGraph | the `interrupt()`/`Command` pattern is exactly built for HITL workflows |
| LLM calls | LangChain + `langchain-groq` | structured output (`with_structured_output`) for reliable agent decisions |
| Inference | Groq | fast enough that a supervisor -> worker -> HITL round trip still feels responsive live |
| Database | PostgreSQL + `pgvector` | one database for relational data AND vector search — no separate vector DB to run |
| Migrations | Alembic | versioned schema changes instead of a single destructive `create_all` |
| Tool boundary | MCP (Model Context Protocol) | genuine tool/agent decoupling, not just a naming convention |
| Automation | APScheduler | in-process, no extra service to run for a prototype |

## 13. Setup

1. **Postgres** — needs the `pgvector` extension available (Postgres 15+ recommended).
   ```bash
   createdb healthcare_ai
   ```

2. **Python env**
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Environment**
   ```bash
   cp .env.example .env
   # fill in DATABASE_URL, DATABASE_URL_SYNC, GROQ_API_KEY, JWT_SECRET_KEY
   ```

4. **Initialize the database** (migrations, via Alembic)
   ```bash
   alembic upgrade head
   ```
   This creates the `vector` extension, all tables, and an IVFFlat index on
   `record_chunks.embedding` for fast semantic search. Future schema changes:
   ```bash
   alembic revision --autogenerate -m "describe the change"
   alembic upgrade head
   ```
   `scripts/init_db.py` still exists as a quick one-shot fallback (`Base.metadata.create_all`,
   no migration history) — use Alembic for anything beyond the first setup.

5. **Run locally**
   ```bash
   source venv/bin/activate
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   Open `http://127.0.0.1:8000` in your browser, then sign up and navigate to
   `/dashboard` or `/chat`.

6. **Optional local developer flow**
   - Start PostgreSQL locally and confirm the database exists: `createdb healthcare_ai`
   - Copy `.env.example` to `.env` and fill in `DATABASE_URL`, `DATABASE_URL_SYNC`, `GROQ_API_KEY`, and `JWT_SECRET_KEY`
   - Use `alembic upgrade head` after any schema changes
   - Re-run the app with `uvicorn app.main:app --reload` after editing code

## 14. Demo script (~3 minutes)

1. "Add my metformin 500mg." -> Medicine Agent proposes `add_medicine` -> approval card appears.
2. Approve -> confirmation message, medicine now shows on `/dashboard`.
3. "Set the dosage to twice daily, morning and evening." -> Dosage Agent proposes `add_dosage` -> approve.
4. "Can you book me an appointment with Dr. Sharma next Tuesday at 10am?" -> Appointment Agent proposes `schedule_appointment` -> **reject** it, to show the reject path also completes cleanly.
5. Try: "What does my last blood test say about my cholesterol?" after uploading a lab report PDF on the dashboard — this goes to the read-only Records Agent (no approval needed, since nothing is written).
6. On any approval card, click **Edit** — the JSON view swaps for editable fields (e.g. fix a wrong dosage amount before it's saved). Click "Save & Approve" — the edited values, not the agent's original proposal, are what gets written. Same `human_approval_node` interrupt path, just `decision: "edited"` instead of `"approved"`.
7. Try a scope-breaking prompt like "What medication should I take for chest pain?" — the input guardrail blocks it before the supervisor ever sees it, since this system doesn't give medical advice.
8. Click "View trace" on any turn to show the full audit log — every guardrail check, routing decision, proposal, human decision, and execution, with latency.
9. Point out the reminders bell icon on `/dashboard` — a background scheduler (not an agent) checks dosage times and upcoming appointments and surfaces them as notifications, entirely outside the HITL-gated write path.
10. On `/dashboard`, edit or delete a medicine/dosage/record directly (no approval card). Contrast this live against step 2 — same underlying tables, but no HITL step, because here the human is the one directly acting, not an agent proposing on their behalf.

## 15. Notes on scope for this prototype

- Semantic search uses `pgvector` + `sentence-transformers` (all-MiniLM-L6-v2) — no external vector DB.
- The MCP layer is real (see `app/mcp_servers/mcp_stdio_server.py`) but wired in-process by default for lower demo latency; swapping to the stdio server is a one-line change in how workers/execute_action source their tools.
- Single-tenant JWT auth via httpOnly cookies — no RBAC/roles yet; every user only ever sees their own rows (enforced at the query level via `user_id` filters).
- Appointment scheduling writes directly to a local `appointments` table — there's no real calendar/EHR integration, and that's said explicitly rather than faked.
- This has been checked for correct syntax (`py_compile` on every file) but has **not** been run end-to-end against a live Postgres + Groq instance in this environment. Run through the demo script once locally before presenting — the most likely friction points are LangGraph's `interrupt()`/`Command` API (it has moved fast across recent versions — double check `langgraph==0.2.62` behaves as expected) and confirming `AsyncPostgresSaver.setup()` creates its checkpoint tables correctly on first run.
```

## 9. Setup

1. **Postgres** — needs the `pgvector` extension available (Postgres 15+ recommended).
   ```bash
   createdb healthcare_ai
   ```

2. **Python env**
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Environment**
   ```bash
   cp .env.example .env
   # fill in DATABASE_URL, DATABASE_URL_SYNC, GROQ_API_KEY, JWT_SECRET_KEY
   ```

4. **Initialize the database** (migrations, via Alembic)
   ```bash
   alembic upgrade head
   ```
   This creates the `vector` extension, all tables, and an IVFFlat index on
   `record_chunks.embedding` for fast semantic search. Future schema changes:
   ```bash
   alembic revision --autogenerate -m "describe the change"
   alembic upgrade head
   ```
   `scripts/init_db.py` still exists as a quick one-shot fallback (`Base.metadata.create_all`,
   no migration history) — use Alembic for anything beyond the first setup.

5. **Run locally**
   ```bash
   source venv/bin/activate
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   Open `http://127.0.0.1:8000` in your browser, then sign up and navigate to
   `/dashboard` or `/chat`.

6. **Optional local developer flow**
   - Start PostgreSQL locally and confirm the database exists: `createdb healthcare_ai`
   - Copy `.env.example` to `.env` and fill in `DATABASE_URL`, `DATABASE_URL_SYNC`, `GROQ_API_KEY`, and `JWT_SECRET_KEY`
   - Use `alembic upgrade head` after any schema changes
   - Re-run the app with `uvicorn app.main:app --reload` after editing code

## 10. Demo script (~3 minutes)

1. "Add my metformin 500mg." -> Medicine Agent proposes `add_medicine` -> approval card appears.
2. Approve -> confirmation message, medicine now shows on `/dashboard`.
3. "Set the dosage to twice daily, morning and evening." -> Dosage Agent proposes `add_dosage` -> approve.
4. "Can you book me an appointment with Dr. Sharma next Tuesday at 10am?" -> Appointment Agent proposes `schedule_appointment` -> **reject** it, to show the reject path also completes cleanly.
5. Try: "What does my last blood test say about my cholesterol?" after uploading a lab report PDF on the dashboard — this goes to the read-only Records Agent (no approval needed, since nothing is written).
6. On any approval card, click **Edit** — the JSON view swaps for editable fields (e.g. fix a wrong dosage amount before it's saved). Click "Save & Approve" — the edited values, not the agent's original proposal, are what gets written. Same `human_approval_node` interrupt path, just `decision: "edited"` instead of `"approved"`.
7. Try a scope-breaking prompt like "What medication should I take for chest pain?" — the input guardrail blocks it before the supervisor ever sees it, since this system doesn't give medical advice.
8. Click "View trace" on any turn to show the full audit log — every guardrail check, routing decision, proposal, human decision, and execution, with latency.
9. Point out the reminders bell icon on `/dashboard` — a background scheduler (not an agent) checks dosage times and upcoming appointments and surfaces them as notifications, entirely outside the HITL-gated write path.
10. On `/dashboard`, edit or delete a medicine/dosage/record directly (no approval card). Contrast this live against step 2 — same underlying tables, but no HITL step, because here the human is the one directly acting, not an agent proposing on their behalf.

## 11. Notes on scope for this prototype

- Semantic search uses `pgvector` + `sentence-transformers` (all-MiniLM-L6-v2) — no external vector DB.
- The MCP layer is real (see `app/mcp_servers/mcp_stdio_server.py`) but wired in-process by default for lower demo latency; swapping to the stdio server is a one-line change in how workers/execute_action source their tools.
- Single-tenant JWT auth via httpOnly cookies — no RBAC/roles yet; every user only ever sees their own rows (enforced at the query level via `user_id` filters).
- Appointment scheduling writes directly to a local `appointments` table — there's no real calendar/EHR integration, and that's said explicitly rather than faked.
- This has been checked for correct syntax (`py_compile` on every file) but has **not** been run end-to-end against a live Postgres + Groq instance in this environment. Run through the demo script once locally before presenting — the most likely friction points are LangGraph's `interrupt()`/`Command` API (it has moved fast across recent versions — double check `langgraph==0.2.62` behaves as expected) and confirming `AsyncPostgresSaver.setup()` creates its checkpoint tables correctly on first run.
