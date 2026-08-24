# CarePilot AI — Product Requirements Document

## 1. Product Definition

CarePilot AI is a caregiving intelligence system for families with an aging parent living at
home. It is **not** a medicine tracker. A medicine tracker is a passive log a caregiver has to
remember to update. CarePilot's job is to watch over a patient in the background and speak up
only when something is actually wrong — the same way a smoke detector earns its place in a
home by being silent 99% of the time.

### 1.1 The two user types

CarePilot has two fundamentally different user types, and the product must be designed
separately for each. They are never the same person, and they never share a login.

**The Caregiver** (the primary product user — signs up, owns the account, pays if this ever
monetizes)
- Adult child of the patient, typically 28–45
- May live WITH the patient, or away in a different city/country — both are real, common
  arrangements, and the product must serve both, not assume distance
- Working full-time (or otherwise occupied enough that continuous attention isn't possible,
  even when physically present in the same house)
- Currently checks in on their parent by phone, or by simply asking in passing if co-resident —
  either way, informally and inconsistently
- Carries ongoing low-grade guilt/anxiety about not knowing if something is wrong, whether
  that's because they're far away or because they're present but can't watch continuously

**The Patient** (affected by the product, but not a conventional "user")
- The aging parent, typically 60–80
- Will not reliably install, log into, or navigate an app
- Already uses WhatsApp / phone calls with their children daily
- May or may not be smartphone/tech-comfortable — design assuming they are NOT, and treat
  tech-comfort as a bonus case, not the baseline

### 1.2 The problem, stated precisely

> "Whether I live with my aging parent or far away, I cannot watch over their health
> continuously — I have a job, I sleep, I get distracted — and I have no reliable way to know
> if something is quietly going wrong until it's already a crisis."

This is deliberately NOT a distance problem. A caregiver who lives with their parent still
can't watch them for the 9 hours they're at work, or notice a slow trend across weeks the way
a system that never gets tired can. Physical distance makes the underlying problem more
extreme, but it isn't the cause of it — the cause is that **continuous vigilance isn't
something any single, busy human can sustain, present or not.** This is an information and
anxiety problem belonging to the Caregiver, not a logging problem. A missed medicine dose is
not the emergency — a missed dose going unnoticed for two weeks is. A single blood pressure
reading is not the emergency — an unwatched trend is.

### 1.3 Who this solves it for

Primary: adult children (India-based or NRI) responsible for an aging parent's wellbeing —
whether co-resident or living apart — who currently rely on informal check-ins, ad hoc phone
calls, or simply being in the house, rather than any reliable system, to know how their parent
is actually doing.

Secondary: siblings/extended family sharing caregiving responsibility for the same
parent; friends in the same life stage recommending the product to each other (organic,
word-of-mouth distribution — not ad-driven).

Adjacent personas worth being aware of, but not designed for in this build: spousal
caregivers (an aging spouse caring for their partner — a common but harder-to-reach segment,
since they're often the least tech-comfortable group); hired/professional attendants who may
be the one physically present day-to-day while the adult child remains the one who signs up,
pays, and receives alerts.

### 1.4 How it solves it — the core mechanism

1. Caregiver creates a **patient profile** for their parent — one-time setup.
2. The patient receives a low-effort daily touchpoint over a channel they already use
   (WhatsApp voice message, or a phone call/IVR fallback) — no app, no login, no typing.
3. A dedicated agent watches the pattern across days/weeks (not single events) and stays
   silent unless something is genuinely worth flagging.
4. When something is worth flagging, an alert reaches the Caregiver directly, in plain
   language, with enough context to decide whether to act.
5. If the Caregiver doesn't respond within a set window, the alert escalates to a secondary
   caregiver or contact.

**Retention model, explicitly:** the app itself is not meant to be a daily-open habit for the
Caregiver. The daily loop that runs is the *background check-in system*, not app usage. The
Caregiver's trust is built passively and spikes into active engagement exactly when the system
catches something — that single moment is the actual retention mechanism, not streaks or
notifications-for-their-own-sake.

---

## 2. Goals

1. A patient can complete a daily check-in in under 20 seconds, with zero app install and zero
   login, via a channel they already use (WhatsApp voice or phone call).
2. A Caregiver receives zero unnecessary notifications on a normal day, and receives one clear,
   actionable alert on a day something is actually abnormal (missed-dose pattern, vitals trend,
   check-in gap).
3. An unanswered alert reaches a second designated contact within a defined escalation window,
   with no manual intervention required.
4. Every AI-proposed change to a patient's medical record (medicine, dosage, appointment)
   requires explicit human approval before it is written — no exceptions, enforced
   structurally, not by prompt instruction.
5. A caregiver can invite a second family member to co-manage the same patient profile, and
   both see the same data and activity history.

## 3. Non-Goals

These are genuine scope boundaries, not things deferred to a later release — everything else
discussed in this document is in scope for this build (see §7).

- **Clinical diagnosis or treatment advice of any kind.** CarePilot never interprets symptoms
  or recommends treatment — this is a hard product boundary. Enforced by the input guardrail
  layer, and by every agent's system prompt.
- **Real-time emergency/911-equivalent response.** The escalation chain notifies family; it
  does not replace emergency services and must never be presented as doing so.
- **AI-scored dietary/meal compliance monitoring.** Analyzing meal photos to judge whether a
  patient's food choices comply with medication or dietary guidance crosses into clinical
  nutrition advice, which conflicts directly with the diagnosis/treatment non-goal above. A
  "take with food" instruction stays a passive reminder, never an AI-evaluated compliance score.
- **US-centric integrations (Epic/MyChart EHR sync, Amazon Pharmacy, Cost Plus Drugs).** Out of
  scope given the primary target market is India-based/NRI families — ABDM/ABHA (§7.5) is the
  correct EHR-equivalent for this market, and PharmEasy/Netmeds/Tata 1mg (§7.5) are the correct
  pharmacy integrations. Revisit only if/when expanding to a US market specifically.

---

## 4. User Stories

### Caregiver
- As a caregiver, I want to create a profile for my parent so that I have one place tracking
  their medicines, appointments, and records.
- As a caregiver, I want to invite my sibling to the same patient profile so that we're not
  duplicating or dropping care tasks.
- As a caregiver, I want my parent to be checked on daily without me having to remember to call
  so that I'm not carrying that mental load alone.
- As a caregiver, I want to be alerted only when something is actually abnormal so that I don't
  learn to ignore notifications.
- As a caregiver, I want to approve or reject any change the AI proposes so that I stay in
  control of my parent's medical record.
- As a caregiver, I want to see why an alert was raised (which pattern, over what period) so
  that I can judge how urgent it is before calling home.
- As a caregiver, I want a second family member notified if I don't respond to an alert in time
  so that something urgent doesn't go unnoticed because I was in a meeting.

### Patient (indirect — via the check-in channel, not an app UI)
- As a patient, I want to answer a daily check-in with a single voice reply so that I don't
  have to learn or open any app.
- As a patient, I want to be reached by phone call if I don't have or use a smartphone so that
  I'm not excluded from the system my children set up for me.

### Edge cases to design for
- Patient doesn't respond to the daily check-in at all (not "took/missed," just silence).
- Patient's voice reply is ambiguous or garbled ("I think so, maybe yesterday").
- Two caregivers approve conflicting changes to the same medicine near-simultaneously.
- Caregiver revokes another caregiver's access to a shared patient profile.
- Patient has no working phone number on file at all (data-entry error at setup).

---

## 5. Daily Flow

**Patient's day:** Receives one WhatsApp voice check-in (or phone call, if no smartphone).
Replies with a short voice note or a spoken response. Total effort: ~15–20 seconds. No app
opened, no login.

**Caregiver's day (normal):** No notification, no app open required. The system's job is to be
invisible on a normal day.

**Caregiver's day (something's off):** Receives one plain-language alert via push/WhatsApp
("Dad's missed his BP tablet 3 times this week — might be worth a call") with enough context to
decide on next action. Can open the app to see the underlying trend, approve/reject any
proposed record change, or just call the patient directly.

---

## 6. Onboarding & Auth

### 6.1 Signup / login (Caregiver only — already built, keep as-is)
- Username + password only. No email verification, OTP, or third-party auth — deliberately
  simple, by product decision.
- JWT stored in an httpOnly cookie.
- No signup/login surface for the Patient at all — they are never expected to authenticate.

### 6.2 Patient profile creation (new — required before the check-in system works)
1. Caregiver signs up / logs in.
2. Caregiver creates a **Patient** record: name, date of birth or approximate age, relationship
   to caregiver, phone number (for WhatsApp/IVR check-ins), primary language.
3. Caregiver adds initial medicines/dosages/known conditions (optional at setup — can be added
   later, including via document upload).
4. Caregiver confirms the patient's phone number and triggers a one-time verification message
   to that number ("Hi, this number will receive daily health check-ins from [Caregiver name]
   via CarePilot AI") — this is both a functional verification step and a consent/transparency
   moment for the patient.
5. Caregiver optionally invites a second caregiver (email/username-based invite) to the same
   patient profile.

### 6.3 Ongoing caregiver invite flow
- Primary caregiver generates a revocable, time-limited invite link scoped to one patient
  profile.
- Invitee signs up (or logs in if already a CarePilot user) and accepts the invite to gain
  access to that patient's data, scoped by role (see §7.4).

---

## 7. Complete Feature Set (single build, not staged releases)

This is being built as one complete system, not a phased rollout. Priority tags (P0/P1/P2)
below indicate criticality to the product vision, not release order — everything in this
section is in scope for this build. The one thing that IS ordered is technical dependency
(§7.0): some features cannot be coded before others exist, regardless of how the work is
scheduled, and that ordering is called out explicitly wherever it applies.

Existing (already built, not repeated here in full): username/password auth, medicine and
dosage CRUD (agent-mediated + direct dashboard), PDF upload with text extraction and pgvector
semantic search, human-in-the-loop approval gate on all agent-proposed writes, input guardrails
(prompt-injection + diagnosis-request blocking), basic adherence streak/supply tracking, a
hardcoded 3-pair drug-interaction check, appointment scheduling via agent + HITL, a background
reminder scheduler, an audit trace log.

### 7.0 Data model foundation — build this first, everything else depends on it

This isn't a "phase" — it's a hard prerequisite. No feature below that references a `Patient`
can be coded before this exists.

- [ ] Introduce a `Patient` entity, separate from `User` (Caregiver). A `User` no longer *is*
      the patient — a `User` *manages* one or more `Patient` profiles.
- [ ] Introduce a `caregiver_patient` join table: many caregivers ↔ many patients, with a role
      per link (`primary` | `secondary` | `viewer`).
- [ ] Migrate `medicines`, `dosages`, `medical_records`, `appointments`, `notifications`,
      `agent_audit_log` to key off `patient_id` instead of `user_id`.
- [ ] Every existing API route and agent tool call updated to resolve "which patient" from the
      caregiver's selected/active patient context, not implicitly from their own user id.

*Acceptance criteria:*
- Given a caregiver with two patient profiles, when they switch between them, all
  medicines/dosages/records/appointments shown are correctly scoped to the selected patient.
- Given two caregivers linked to the same patient, both see identical data for that patient.

### 7.1 Patient check-in system

**P0**
- [ ] WhatsApp Business API integration for outbound daily check-in messages to the patient's
      phone number. **Dependency note:** WhatsApp Business API requires template message
      approval from Meta before any message can be sent in production — start this application
      early since it's an external approval process, not something more coding speeds up.
- [ ] Voice-note reply ingestion: transcribe the patient's spoken reply via speech-to-text.
- [ ] Check-in response parser (agent): interpret transcribed/text replies into a structured
      `taken` | `missed` | `unclear` | `no_response` log entry per scheduled dose or general
      wellness check.
- [ ] Fallback IVR/phone-call check-in for patients without WhatsApp/smartphone access.
- [ ] Secure caregiver-patient linking — **the current public, unauthenticated
      `/caregiver/{username}` route is a live data-exposure issue and needs replacing
      regardless of anything else in this list.** Replace with a random, revocable, per-patient
      share token.

**P1**
- [ ] Lightweight optional patient-facing app view (large text, today's medicines only,
      one-tap confirm) for the tech-comfortable subset of patients.
- [ ] Multi-language check-in messages (Hindi + at least one additional regional language).

**P2**
- [ ] Real-time streaming voice agent (e.g., WebRTC-based, OpenAI Realtime API or equivalent)
      as an alternative to the async WhatsApp-voice-note check-in. Deliberately lower priority
      than the async flow: it requires the patient to answer a live call at a specific moment,
      a worse fit for a non-tech-fluent elderly patient than replying on their own time, and
      it's meaningfully more expensive/complex to build.

*Acceptance criteria:*
- Given a patient with a verified phone number, when the scheduled check-in time arrives, a
  WhatsApp message is sent and a reply within N hours is correctly logged as taken/missed/unclear.
- Given no reply within the check-in window, the system logs `no_response`, distinguishable
  from an explicit "missed" reply in later pattern analysis.
- Given the patient has no WhatsApp-capable number on file, the system falls back to a phone
  call check-in automatically.

### 7.2 Intelligence and alerting

**P0**
- [ ] A dedicated pattern-watching agent, run on a schedule, separate from the request-handling
      supervisor/worker agents — its only job is longitudinal analysis of check-in and
      adherence history per patient.
- [ ] Configurable threshold + trend rules (e.g., 3+ missed/unclear check-ins in 7 days; N
      consecutive `no_response` days; vitals reading outside a defined range for 2+ consecutive
      entries).
- [ ] Alert delivery to the primary caregiver via push notification and/or WhatsApp, in plain
      language, referencing the specific pattern detected.
- [ ] Escalation chain: if no caregiver acknowledgment within a configurable window, notify the
      secondary caregiver/contact on file.
- [ ] Replace the hardcoded 3-pair drug-interaction dictionary with a real interaction dataset
      (e.g., RxNav or openFDA), surfaced as a proposed flag through the existing HITL approval
      flow, not an unreviewed auto-block.

**P1**
- [ ] Correlation surfacing: link an adherence dip to a vitals movement in the same window,
      shown together in the alert, not just as two separate data points.
- [ ] Weekly caregiver digest (proactive summary, pushed — not a dashboard the caregiver has to
      remember to open).
- [ ] Polypharmacy flag (patient on 5+ concurrent medicines) surfaced as a review prompt.

**P2**
- [ ] Environmental pattern correlation: cross-reference a patient's historical symptom logs
      against external environmental data (e.g., pollen count, humidity, AQI) for known
      trigger-sensitive conditions (asthma, arthritis), proactively surfacing a same-day
      heads-up. **Dependency note:** needs enough historical symptom-log data per patient to be
      meaningful, so this naturally activates later even though the code can ship alongside
      everything else.

*Acceptance criteria:*
- Given a patient with 3 missed check-ins in the trailing 7 days, an alert is generated and
  sent to the primary caregiver within one scheduler cycle.
- Given an alert is sent and not acknowledged within the configured escalation window, the
  secondary contact receives the same alert automatically, with no manual trigger required.
- Given a normal week (no threshold breached), zero alerts are sent — this must be verified as
  explicitly as the alerting path itself.

### 7.3 Document intelligence

**P1**
- [ ] OCR support for photographed/handwritten prescriptions (current pipeline assumes
      clean-text PDFs only).
- [ ] Auto-reconciliation on upload: new record compared against current medicine list, agent
      proposes discrepancy flags/updates through the existing HITL flow rather than silently
      filing the document.
- [ ] Structured lab-value extraction (e.g., HbA1c, creatinine, BP readings) stored as
      trackable time-series data, not just embedded free text.
- [ ] One-click doctor-visit prep/summary export (current medicines, conditions, recent vitals,
      adherence snapshot).

**P2**
- [ ] Post-visit reconciliation: caregiver relays what the doctor said (typed or voice), agent
      proposes resulting medicine/appointment updates via the standard approval flow.
- [ ] Photo-based pill identification: caregiver or patient photographs a loose/unlabeled pill;
      computer vision identifies it and cross-references against the patient's active
      prescriptions, flagging any mismatch through the standard HITL flow (identification only
      — never a dosing or safety judgment call made autonomously).

### 7.4 Family coordination

**P1**
- [ ] Caregiver invite flow (see §6.3), scoped per patient, with role-based permissions
      (`primary` can edit/approve; `secondary`/`viewer` permissions TBD — see Open Questions).
- [ ] Shared activity feed per patient — visible to every linked caregiver.
- [ ] Task assignment between caregivers (e.g., "pick up refill," "attend Friday appointment")
      with completion tracking.

### 7.5 India-specific value-add

**P2**
- [ ] ABDM/ABHA health ID linking.
- [ ] Generic medicine substitute suggestions with estimated savings.
- [ ] Medicine spend tracking per patient.
- [ ] Pharmacy ordering integration (e.g., PharmEasy/Netmeds/Tata 1mg): when a medicine's
      tracked supply drops below its refill threshold, the system proposes re-ordering it to
      the patient's door — same HITL approval gate as any other proposed action, never an
      autonomous purchase.
- [ ] Teleconsultation booking, agent-mediated.
- [ ] Insurance-claim document organizer.

### 7.6 Device and emergency infrastructure

**P2**
- [ ] Wearable/health-platform integration (e.g., Apple Health, smartwatch-based BP monitors,
      glucometers) for automatic vitals capture, feeding the same adherence-correlation
      analysis in §7.2 — e.g., surfacing "resting heart rate has improved since adherence to
      [medicine] became consistent" as a positive-reinforcement signal to the caregiver, not
      just a raw data feed.
- [ ] Fall detection via wearable, wired into the §7.2 escalation chain.
- [ ] One-tap emergency mode: notify all linked caregivers, share patient location, surface
      doctor-ready summary in one screen.
- [ ] Local hospital/ambulance integration (city-by-city rollout).

---

## 8. Success Metrics

### Leading indicators (days–weeks post-launch)
- **Check-in response rate**: % of daily check-ins the patient responds to (target: >70% within
  the check-in window, post-onboarding week).
- **Alert precision**: % of sent alerts a caregiver marks as "useful" vs. "not useful" in-app
  (target: >80% useful — a low number here means thresholds are too sensitive).
- **Alert-to-acknowledgment time**: median time from alert sent to caregiver acknowledgment.
- **Escalation trigger rate**: % of alerts that go unacknowledged and escalate (track as a
  health metric — very high or near-zero both suggest miscalibration).
- **Setup completion rate**: % of caregivers who complete patient profile creation once started.

### Lagging indicators (weeks–months)
- **Multi-caregiver adoption rate**: % of patient profiles with 2+ linked caregivers (proxy for
  organic word-of-mouth distribution working as intended).
- **30/60/90-day caregiver retention**: are caregivers still linked/active, not necessarily
  opening the app daily (per the retention model in §1.4).
- **"Caught something" rate**: qualitative/self-reported instances where an alert led to a
  caregiver taking an action they wouldn't have otherwise (survey-based initially).

---

## 9. Open Questions

- **[Product/Legal]** What are the data-privacy and consent requirements for recording and
  transcribing a patient's voice check-ins, especially for a patient who isn't the one who
  signed up? Needs explicit patient-facing consent language at the profile-verification step
  (§6.2 step 4), and likely legal review given health-adjacent data at scale.
- **[Product]** What exact permission differences exist between `primary`, `secondary`, and
  `viewer` caregiver roles (§7.4)? Can a `secondary` caregiver approve a HITL action, or only
  `primary`?
- **[Engineering]** WhatsApp Business API has message-template approval requirements and
  per-message cost at scale — what's the cost model at "lakhs of users," and does that change
  the check-in frequency/design?
- **[Engineering]** Speech-to-text for check-in replies needs to handle Hindi/regional-language
  voice notes accurately — which provider, and what's the acceptable error rate before a
  misheard "haan" (yes) becomes a false "missed dose" alert?
- **[Product]** What's the actual escalation window (minutes/hours) before a secondary contact
  is notified? Too short risks false urgency; too long defeats the purpose.
- **[Data]** Where do drug-interaction and dosage-safety datasets come from for the Indian
  market specifically (many products like RxNav are US-centric) — is there an equivalent
  India-relevant source, or does this need clinical review either way?

---

## 10. Build Order

This is one build, not a staged release — but code still has to be written in an order that
respects real dependencies. This is that order, not a rollout plan:

1. **§7.0 data model** (`Patient` entity, `caregiver_patient` join table, everything migrated
   off `user_id` onto `patient_id`) — nothing else in this document compiles or makes sense
   without this existing first.
2. **The security fix in §7.1** (replacing the public `/caregiver/{username}` route) — flagged
   separately because it's a live exposure in the current codebase, independent of any new
   feature work; fix it alongside §7.0, don't wait.
3. From there, the rest of §7 can be built in parallel by area (check-in system, alerting,
   document intelligence, family coordination, India-specific integrations, device/emergency
   infrastructure) since they don't block each other once §7.0 exists — **except** that the
   alerting agent (§7.2) needs check-in data (§7.1) to actually have something to analyze, so
   it should land second even if coded concurrently.
4. External dependencies that need lead time regardless of coding order: WhatsApp Business API
   template approval (§7.1), and sourcing an India-relevant drug-interaction dataset (§7.2,
   see Open Questions) — start these early since they're not blocked by writing code, but
   nothing downstream works without them either.

---

## 11. Non-Negotiable Product Principles (carry into every feature)

1. **No agent writes to a patient's record without explicit human approval.** This must remain
   structurally enforced (graph topology, not prompt instruction) as new agents are added —
   including the §7.2 pattern-watching agent, which only ever *proposes* alerts/flags, never
   modifies data itself.
2. **No medical diagnosis or treatment advice, ever**, regardless of feature.
3. **The patient should never be required to install an app, remember a login, or learn a new
   interface** to be part of the system. Any patient-facing feature must degrade gracefully to
   "a phone call" as the baseline case.
4. **Silence is a feature.** A day with no alerts is the system working correctly, not the
   system being idle — resist any design pressure to manufacture engagement/notifications for
   their own sake.

## 12. update the readme when done building & push the code to github repo. Also, in readme, include detailes about the product, who is this for, what problem it solves, for whom, what value this brings to the end user, how it works(architecture), tech stack, explain every tech decision, user flow end to end, features list, how to setup and run.