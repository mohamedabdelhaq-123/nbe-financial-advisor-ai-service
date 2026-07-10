# Feature Specification: Agentic Pipelines, Analytics & Integration (Phase 2)

**Feature Branch**: `feat/database` (concurrent) — Phase 2 tracked in `specs/002-phase2-agentic-pipelines/`

**Created**: 2026-07-10

**Status**: Draft

**Source Plan**: `specs/001-ai-service-scaffolding/plan.md` — sections **2.1 – 2.6** only

**Input**: User description: "Generate the spec for Phase 2 (sections 2.1–2.6) of the plan. First reconcile the plan with the current state of the project, mainly the backend_db. Phase 1 (1.1–1.4) is being implemented concurrently and is NOT merged — treat Phase 1 as available via interfaces, not implementations."

---

## Overview

Phase 2 turns the scaffolded AI service into a working financial advisor. It delivers the
conversational assistant (a single orchestrator delegating to specialised sub-capabilities with
persistent memory), the guided budget planner, the product-recommendation engine, the deterministic
analytics pipelines that power dashboards and ground the assistant's answers, and the end-to-end
testing and CI hardening needed to integrate safely with the Django backend.

The consumer of every capability in this spec is the **Django backend** (an internal, authenticated
caller); the ultimate beneficiary is the **end user** of the personal-finance product, reached
*through* Django. This service is never exposed to the end user directly.

> **Scope guard**: Phase 1 items (1.1–1.4: project infrastructure, database modelling & migrations,
> document extraction/normalization, embedding service) are **out of scope** for this spec and are
> being built concurrently. They are consumed here as **interfaces**, enumerated under
> *Dependencies*. This spec adds no requirements on Phase 1 work.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Conversational financial assistant (Priority: P1)

Through the Django backend, an end user holds a natural-language conversation with the assistant
about their finances. A single orchestrator interprets each message, routes it to the right
specialised capability (spending analysis, budget planning, or product recommendation), and streams
back a grounded, plain-language reply. The conversation remembers earlier turns, so the user can ask
follow-ups without repeating themselves.

**Why this priority**: This is the flagship capability of the service and the primary reason Phase 2
exists. It is the one slice that, on its own, delivers a usable advisor.

**Independent Test**: Send a first-turn request carrying user context plus a spending question and
confirm a grounded, streamed reply that cites the user's own figures; send a follow-up on the same
conversation id (context-free) and confirm the assistant still "remembers" the thread. Fully testable
with a mock LLM and fixture backend data.

**Acceptance Scenarios**:

1. **Given** a first-turn request with `is_first_turn=true`, a conversation id, user context, and a
   spending question, **When** it is processed, **Then** the reply is streamed incrementally, is
   grounded in the user's data, and cites the source rows used.
2. **Given** an existing conversation id, **When** a follow-up message arrives carrying only
   `{conversation_id, user_id, message}`, **Then** the assistant answers using remembered prior turns
   without the caller re-sending context.
3. **Given** a message whose intent is budget planning, **When** the orchestrator classifies it,
   **Then** it is routed to the planning capability rather than answered directly.
4. **Given** a spending question for which no underlying data exists, **When** it is processed,
   **Then** the assistant states that the data is unavailable and does **not** invent figures.
5. **Given** a request with `refresh_context=true`, **When** it is processed, **Then** the assistant
   reloads the user's current context before answering.
6. **Given** a reply that offers financial advice, **When** it is returned, **Then** it carries an
   appropriate advice disclaimer and contains no personally identifying data beyond what the caller
   supplied.

---

### User Story 2 - Automated financial insight pipelines (Priority: P2)

After a bank statement is ingested (Phase 1), the Django backend triggers background analytics so the
user's dashboard and the assistant's analysis answers are backed by pre-computed, trustworthy figures:
monthly spending summaries, recurring-charge detection, and anomaly flags. All computation is
deterministic — no language model is involved — and results are **returned to Django to persist**.

**Why this priority**: These insights power the dashboard and ground User Story 1's analysis answers.
They are independently valuable and independently testable, but the assistant can still function on
fixture data without them, so they rank below the flagship conversation.

**Independent Test**: Feed a fixed set of transactions for a `(user, account, month)` and confirm the
returned monthly summary, recurring charges, and anomaly flags are correct and identical on every run.

**Acceptance Scenarios**:

1. **Given** a set of transactions for a `(user_id, account_id, month)`, **When** a monthly-summary is
   requested, **Then** the service returns a deterministic aggregation (totals per category, net,
   etc.) plus its embedding, for Django to persist.
2. **Given** transactions containing a charge that repeats at a regular cadence, **When** recurring-
   charge detection runs, **Then** that charge is returned as a recurring charge and one-off charges
   are not.
3. **Given** a category whose spending contains a statistical outlier, **When** anomaly detection runs,
   **Then** the outlier is returned as an anomaly flag and normal spending is not flagged.
4. **Given** the same input transactions, **When** any analytics job runs twice, **Then** it produces
   byte-identical results (no randomness, no model calls).
5. **Given** a post-ingestion trigger, **When** it is processed, **Then** the relevant analytics are
   computed and returned; the service writes nothing to backend-owned tables.

---

### User Story 3 - Guided budget planning (Priority: P2)

An end user asks for help building a budget. The service runs a short guided questionnaire (asking
only what it still needs to know), then produces a set of budget allocations that always add up to
exactly 100% of the user's planned spend. This is reachable both inside a conversation (via the
orchestrator) and through dedicated endpoints Django can call directly.

**Why this priority**: A concrete, high-value advisor capability, but narrower than the general
assistant and dependent on the same conversational plumbing.

**Independent Test**: Drive the questionnaire endpoint with a partial user context and confirm it
returns the next unanswered question; submit a full set of answers to the generate endpoint and
confirm the returned allocations sum to exactly 100%.

**Acceptance Scenarios**:

1. **Given** a user context missing some planning inputs, **When** the next-question endpoint is
   called, **Then** it returns the single most relevant unanswered question.
2. **Given** the questionnaire has already asked the maximum number of questions, **When** another
   question is requested, **Then** the service stops asking and proceeds to generate a plan.
3. **Given** a complete set of answers, **When** a plan is generated, **Then** the returned budget
   allocations sum to exactly 100% before the response is returned.
4. **Given** the same planning request reached via the conversation orchestrator, **When** processed,
   **Then** it yields an equivalent, validated 100% plan.

---

### User Story 4 - Personalised product recommendations (Priority: P3)

When a user's situation matches a known financial need, the service recommends relevant bank products.
It matches the user's expressed or inferred need against a curated knowledge base of problem
statements and returns the best-matching products with confidence scores. Each recommendation shown is
logged for later analysis.

**Why this priority**: Valuable for the business but the least critical of the advisor capabilities and
not required for the assistant to be useful.

**Independent Test**: Query the match endpoint with a need description and confirm it returns the
top-k products ranked by similarity, and that a log entry is recorded for each.

**Acceptance Scenarios**:

1. **Given** a populated problem-statement knowledge base, **When** a need is submitted for matching,
   **Then** the top-k products are returned ranked by similarity score.
2. **Given** a recommendation is returned to the caller, **When** it is produced, **Then** a
   recommendation log entry (user, product, matched query, score, timestamp) is written to the
   service-owned store.
3. **Given** a need that matches nothing above the similarity threshold, **When** matching runs,
   **Then** an empty result is returned without error.
4. **Given** an operator needs to (re)populate the knowledge base, **When** the seed utility is run,
   **Then** problem statements and their embeddings are loaded — via an admin utility, never a runtime
   endpoint.

---

### User Story 5 - Integration & operational readiness (Priority: P3)

The backend team can integrate against Phase 2 with confidence: every capability is covered by
deterministic, mock-first automated tests against a real Postgres, and CI enforces the security and
quality gates the constitution requires before anything merges.

**Why this priority**: A cross-cutting enabler. It ships alongside the features rather than delivering
end-user value on its own, so it is sequenced last.

**Independent Test**: Run the full test suite offline (no real model or network calls) and confirm it
passes against a Testcontainers Postgres; run CI and confirm mypy, secret scanning, dependency-
vulnerability scanning, and the container image build all gate the merge.

**Acceptance Scenarios**:

1. **Given** the test suite, **When** it runs, **Then** it issues no real model or external-network
   calls and is fully deterministic.
2. **Given** every Phase 2 endpoint, **When** called without a valid bearer token, **Then** the
   request is rejected (probes remain the only unauthenticated routes).
3. **Given** the CI pipeline, **When** it runs, **Then** type-checking, secret scanning, dependency-
   vulnerability scanning, and container image build all execute and block on verified findings.
4. **Given** the pre-existing probe/auth/migration tests, **When** the Phase 2 changes land, **Then**
   those tests still pass.

---

### Edge Cases

- **No data for a question**: the assistant states data is unavailable rather than fabricating figures.
- **Very long conversation**: when history grows past the configured threshold, older turns are
  summarised and only a recent window is kept in the model's context — the conversation keeps working.
- **First turn missing context**: a first turn that omits required initial context is rejected with a
  clear error.
- **Contradictory or sparse planning answers**: the planner still returns a valid 100% plan (or keeps
  asking, up to the question cap) rather than an invalid allocation.
- **Empty / tiny transaction set**: analytics jobs return empty or zeroed results without error and
  flag nothing spuriously.
- **Duplicate analytics triggers**: re-triggering post-ingestion for the same period yields the same
  result (idempotent) and creates no duplicate side effects.
- **Backend database unreachable**: capabilities that read backend data fail gracefully with a service-
  unavailable response instead of hanging or returning wrong data.
- **Recommendation with no match above threshold**: returns an empty ranked list, not an error.
- **Streaming interrupted**: a dropped stream does not corrupt persisted conversation memory.

---

## Requirements *(mandatory)*

### Functional Requirements

#### Conversational assistant (User Story 1)

- **FR-001**: The service MUST expose a single authenticated conversational entry point that accepts a
  user message tied to a conversation id and returns the assistant's reply.
- **FR-002**: A single orchestrator MUST classify the intent of each message and route it to exactly
  one specialised capability: spending analysis, budget planning, or product recommendation (falling
  back to a general response when no specialised intent applies).
- **FR-003**: The service MUST persist conversation memory keyed by conversation id so that later
  turns are answered with knowledge of earlier turns.
- **FR-004**: On the first turn the caller supplies initial user context; on subsequent turns the
  caller supplies only conversation id, user id, and message, and the service MUST rely on persisted
  memory for the rest.
- **FR-005**: The assistant's reply MUST be streamed incrementally to the caller.
- **FR-006**: When conversation history exceeds a configured size, the service MUST summarise the
  oldest turns into a compact summary and keep only a recent window in the model's working context, so
  context stays bounded regardless of conversation length.
- **FR-007**: The spending-analysis capability MUST base every figure it states on retrieved source
  rows, MUST cite those sources in the response, and MUST NEVER fabricate financial figures; when the
  data is missing it MUST say so.
- **FR-008**: The service MUST honour a `refresh_context` request flag by reloading the user's current
  context before answering.
- **FR-009**: Replies that offer financial advice MUST carry an appropriate disclaimer, and prompts
  sent to the language model MUST be free of personally identifying data beyond what the caller
  supplied.
- **FR-010**: Every privileged action MUST be recorded to the service-owned audit log.

#### Budget planning (User Story 3)

- **FR-011**: The planning capability MUST run a multi-turn questionnaire that asks only for
  information still missing from the user's context, bounded by a maximum number of questions.
- **FR-012**: The service MUST generate budget allocations that sum to exactly 100%, and MUST validate
  this internally before returning any plan.
- **FR-013**: Budget planning MUST be reachable both through the conversation orchestrator and through
  dedicated authenticated endpoints (next-question and generate-plan) that Django can call directly.
- **FR-014**: The next-question and generate-plan endpoints MUST be stateless given the context and
  answers supplied in the request.

#### Product recommendations (User Story 4)

- **FR-015**: Given a described or inferred user need, the service MUST return the top-k best-matching
  products ranked by similarity against the service-owned problem-statement knowledge base.
- **FR-016**: The service MUST log each recommendation shown (user, product, matched query, similarity
  score, timestamp) to the service-owned recommendation log.
- **FR-017**: The service MUST return an empty ranked result (not an error) when no product matches
  above the configured similarity threshold.
- **FR-018**: An admin seed utility (not a runtime endpoint) MUST be provided to populate the problem-
  statement knowledge base and its embeddings.

#### Analytics pipelines (User Story 2)

- **FR-019**: The service MUST compute a deterministic monthly spending summary for a given
  `(user_id, account_id, month)` from transaction data and MUST return the summary together with its
  embedding for Django to persist.
- **FR-020**: The service MUST detect recurring charges across a user's transactions and return them
  for Django to persist.
- **FR-021**: The service MUST detect per-category statistical spending anomalies and return anomaly
  flags for Django to persist.
- **FR-022**: The service MUST expose authenticated endpoints to trigger post-ingestion analytics,
  monthly-summary computation, and anomaly checks.
- **FR-023**: Analytics computations MUST NOT involve any language-model call and MUST be deterministic
  (identical inputs produce identical outputs).
- **FR-024**: Analytics endpoints MUST **return** their results to the caller; the service MUST NOT
  write any backend-owned table (see *Data Ownership* below).

#### Cross-cutting integration & readiness (User Story 5)

- **FR-025**: Every Phase 2 endpoint MUST require a valid shared-secret bearer token; only the
  liveness/readiness probes remain unauthenticated.
- **FR-026**: All automated tests MUST be deterministic and mock-first for the language model and the
  embedder, issuing no real model or external-network calls, with mock responses matching the
  production response shape.
- **FR-027**: Integration tests MUST run against a real Postgres provisioned via Testcontainers,
  covering both the service-owned database and a backend-database stand-in exercised read-only.
- **FR-028**: CI MUST run type-checking, secret scanning, dependency-vulnerability scanning, and a
  container image build, and MUST block on verified findings.
- **FR-029**: The pre-existing probe, auth, and migration tests MUST continue to pass after Phase 2
  lands, and configuration examples MUST be updated to cover any new settings.

#### Data ownership & boundaries (applies across all stories)

- **FR-030**: The service MUST read backend-owned tables only through the read-only access path and
  MUST define no write path against them — including no writes to analytics results or embedding
  columns on backend tables. All such results are returned to Django to persist.
- **FR-031**: The service MUST write only to its own tables: the problem-statement knowledge base,
  the recommendation log, the audit log, and its conversation-memory store.
- **FR-032**: The service MUST name, and read via hand-written read-only models, exactly the backend
  tables it depends on (see *Key Entities → Backend read dependencies*).

### Key Entities *(include if feature involves data)*

**Service-owned (this service persists these):**

- **Conversation memory**: durable per-conversation state keyed by conversation id — the running
  message history plus advisor working state (user context, current stage, detected intent, collected
  planner answers, count of questions asked, and the source references cited in replies).
- **Problem statement (knowledge base)**: a curated need description paired with the product it maps to
  and its embedding; the corpus the recommendation engine searches. *(Table created in Phase 1;
  populated and queried here.)*
- **Recommendation log**: a record of each recommendation shown — user, product, matched query,
  similarity score, and timestamp. *(Table created in Phase 1; written here.)*
- **Audit log entry**: a record of each privileged action — user, action, detail, timestamp. *(Table
  created in Phase 1; written here.)*

**Returned to Django (computed here, persisted by the backend — never written by this service):**

- **Monthly summary**: deterministic aggregation of a user/account's spending for a month, plus its
  embedding.
- **Recurring charge**: a charge detected as repeating at a regular cadence.
- **Anomaly flag**: a per-category spending outlier.
- **Budget allocation**: a category-to-percentage allocation whose set sums to exactly 100%.

**Backend read dependencies (read-only; hand-written models added to `app/backend_db/models.py`):**
`transactions`, `monthly_summaries`, `bank_accounts`, `budgets`, `budget_allocations`, `products`,
`users`, and the analytics-result tables Django owns (`recurring_charges`, `anomaly_flags`) when the
assistant needs to read prior results.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a spending question with available data, the assistant returns a grounded answer in
  which **100%** of stated figures are traceable to a cited source row — **zero** fabricated figures
  across the test suite.
- **SC-002**: **100%** of generated budget plans sum to exactly 100% before being returned.
- **SC-003**: The budget questionnaire asks **no more than the configured maximum (7)** questions
  before producing a plan.
- **SC-004**: Analytics jobs are fully deterministic — the same inputs produce identical outputs on
  **every** run, with no model involvement.
- **SC-005**: A conversation continues to function correctly beyond **40** messages, with bounded
  working context (older turns summarised, recent window retained).
- **SC-006**: A follow-up turn is answered correctly using persisted memory when the caller sends
  **only** conversation id, user id, and message (no re-sent context).
- **SC-007**: The recommendation engine returns a ranked top-k result, and **every** recommendation
  shown produces exactly one log entry.
- **SC-008**: **100%** of Phase 2 endpoints reject requests lacking a valid token; probes remain the
  only unauthenticated routes.
- **SC-009**: The full test suite passes offline with **zero** real model or external-network calls,
  against a real (Testcontainers) Postgres.
- **SC-010**: CI blocks a merge on any verified secret, dependency vulnerability, type error, or failed
  image build.
- **SC-011**: The service writes to **zero** backend-owned tables across all Phase 2 operations
  (verified by the read-only access path and tests).

## Assumptions

- **Phase 1 is consumed as interfaces, not built here.** Phase 2 assumes the Phase 1 slices (project
  infrastructure, own/backend DB setup, migrations for the AI-owned tables and checkpointer, document
  extraction/normalization, and the embedding service) are available behind the interfaces listed
  under *Dependencies*. No Phase 1 task is (re)specified here.
- **Backend database is strictly read-only (reconciliation decision).** The plan's "Agreed Decisions"
  and §2.5 describe the service writing analytics results and embedding columns directly to the backend
  DB. This is superseded to match Constitution IV (NON-NEGOTIABLE) and the current
  `app/backend_db/` implementation: the service **computes and returns** all analytics results and
  embeddings for Django to persist, and never writes any backend-owned table. Chosen by the user during
  reconciliation.
- **Derived analytics tables (`monthly_summaries`, `recurring_charges`, `anomaly_flags`) are
  backend-owned.** The service returns computed rows; Django persists them. No new AI-owned analytics
  tables are introduced in Phase 2.
- **Slice layout follows the actual codebase**, not the plan's illustrative paths: feature slices live
  under `app/features/<slice>/` (e.g. `app/features/chat`, `app/features/plan`,
  `app/features/recommendations`, `app/features/analytics`), and backend read models live in
  `app/backend_db/models.py` (not `app/core/backend_models.py`).
- **Analytics are triggered by Django** through the internal endpoints; this service runs no internal
  scheduler/cron. "Background" means "not computed on-demand inside a chat turn."
- **The language-model provider is config-driven** (base URL and model name), and tests run in mock
  mode; no capability hardcodes a provider or issues real model calls in CI.
- **Product recommendation similarity search runs over the service-owned knowledge base**
  (`ai_problem_statements`); transaction/summary embeddings, if needed for retrieval, are read
  read-only from wherever Django persists them.
- **The chat state-design reference** cited by the plan
  (`consolidated files/problems-to-solve/Chat_State_Design.md`) is **absent from the repository**; the
  conversation-state fields are taken from plan §2.1 (messages, user_context, stage, intent,
  planner_answers, questions_asked, message_references).
- **Similarity thresholds, top-k, summarisation/trim sizes (40/20), and the planner question cap (7)**
  are configurable; the numeric defaults above come from the plan.

## Dependencies

**Consumed Phase 1 interfaces (must exist before Phase 2 integration completes):**

- Own database access — `OwnBase` / `get_own_session()` (`app/core/db.py`), read-write, Alembic-managed.
- Backend database read access — `BackendBase` / `get_backend_session()` (`app/backend_db/`),
  read-only, Alembic-excluded.
- Bearer-token auth dependency — `require_token()` (`app/core/security.py`).
- Config-driven LLM access — `get_chat_model()` and `use_mock_llm` (`app/core/config.py`,
  `app/core/llm.py`).
- Embedding service — `POST /internal/embed` and the embedding configuration (model, base URL) added
  in Phase 1 §1.4/§1.1.
- Migrations that create the AI-owned tables (`ai_problem_statements`, `ai_recommendation_logs`,
  `ai_audit_log`) and document the conversation-memory/checkpointer tables (Phase 1 §1.2).
- Document normalization output (`transactions` populated in the backend) as the input to analytics.

**New capabilities Phase 2 introduces (in the plan, not yet in the codebase):**

- Conversation-memory persistence in the service-owned database (checkpointer-backed), initialised at
  startup.
- Orchestrator + specialised sub-capabilities and their wiring.
- Similarity search over the service-owned problem-statement knowledge base.
- CI steps for type-checking, secret scanning, dependency-vulnerability scanning, and image build; the
  Testcontainers backend-database stand-in; and mock embedder fixtures.

**External dependency:** the Django backend triggers analytics, proxies the streamed conversation
responses to the end user, persists all returned results, and performs its own second-layer validation
of budget allocations.
