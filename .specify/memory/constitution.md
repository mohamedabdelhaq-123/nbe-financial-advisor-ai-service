<!--
SYNC IMPACT REPORT
==================
Version change: 2.2.0 → 2.3.0
Rationale: MINOR. Principle III's absolute "redact before inclusion in LLM
prompts" rule is replaced by a narrow, conditional exception covering the live
model-inference call only, while the minimization requirement for logs AND
telemetry/observability exports (e.g. an LLM tracing backend) is preserved and
made explicit. Mirrors the 2.2.0 precedent set on Principle IV: an absolute
rule becomes "required by default, with a narrow, explicitly-scoped exception,"
not a removal — enforced behavior for every case outside that exception is
unchanged, and the exception itself is bounded to a specific, checkable
condition (self-hosted model backend) rather than granted unconditionally.

Modified principle (this amendment):
  - III. Data Protection & Compliance (NON-NEGOTIABLE) — the live LLM
    inference request/response is now exempt from prompt-level redaction ONLY
    while the configured model backend is self-hosted infrastructure under
    this organization's control; this reflects that (a) the service's core
    function (financial analysis, statement normalization) structurally
    requires full-fidelity input to work, and (b) the prior rule was never
    actually enforced anywhere in the codebase (a `strip_pii()` helper exists
    in `app/features/chat/guards.py` but is dead code — never called from any
    prompt-construction site). The exception is scoped to the inference call
    only: any secondary copy of that same content — logs, telemetry, or an
    observability/tracing export (e.g. a self-hosted Langfuse instance) —
    remains subject to the unmodified, unconditional minimization
    requirement. The exception is void the moment a non-self-hosted backend
    is configured (`OPENAI_BASE_URL`/`EMBEDDING_BASE_URL` pointed at a real
    external vendor), since Principle VI deliberately keeps the backend
    swappable via config alone, with no code change.

Trigger: while planning the LLM-observability (Langfuse tracing) feature, the
plan's Constitution Check surfaced a real contradiction — auto-instrumentation
must either hide entire prompt/response content (defeating the feature's
purpose) or export it unredacted (violating Principle III as previously
worded). Investigation found Principle III's "redact before LLM prompts"
clause was never implemented for any existing feature, and that the actual
production plan is a self-hosted model backend, not a third-party vendor call.
The requester asked that the principle be amended to reflect what's actually
enforceable and necessary, rather than holding one new feature (tracing) to a
stricter bar than the rest of the codebase, or silently dropping compliance
protection for a hosted-vendor scenario that remains structurally possible via
config alone.

Principle mapping (stable since 1.0.0, extended 2.1.0, IV expanded 2.2.0, III
amended 2.3.0):
  - I. Mandatory Automated Testing
  - II. Security & Secrets Discipline
  - III. Data Protection & Compliance (NON-NEGOTIABLE) (amended 2.3.0)
  - IV. Data Ownership & Access Boundaries (expanded 2.2.0)
  - V. Feature-Bounded Modular Architecture
  - VI. LLM & Agent Architecture
  - VII. Operational Readiness & Fail-Fast Configuration
  - VIII. Library-First, Minimal Implementation (added 2.1.0)

Sections: unchanged (Technology & Quality Standards; Development Workflow &
Quality Gates). Removed sections: none.

Templates checked for consistency:
  ✅ .specify/templates/plan-template.md — Constitution Check gate is generic
     ("[Gates determined based on constitution file]"), derived fresh from
     the constitution at plan time; the Langfuse feature's plan.md already
     produced a Principle-III gate row that this amendment now makes
     satisfiable without contradiction. No template change needed.
  ✅ .specify/templates/spec-template.md — no mandatory-section conflicts.
  ✅ .specify/templates/tasks-template.md — no new task category required.
  ✅ .specify/templates/checklist-template.md — no conflicts.

Follow-up TODOs:
  - The pre-existing gap this amendment surfaced — no prompt-level redaction
    exists anywhere today, self-hosted or not (`strip_pii()` is dead code) —
    is NOT resolved by this amendment and remains open. It no longer blocks
    the Langfuse feature, whose redaction work is now correctly scoped to the
    export/telemetry boundary only, but wiring real minimization into the
    prompt-construction layer (chat analysis, ingestion normalization, plan
    generation) is separate, tracked follow-up work.
Deferred (by decision, not omission): the Django-facing API shape — this
constitution is intentionally API-shape-agnostic.
-->

# NBE AI-PFM Service Constitution
<!-- Internal FastAPI AI service for the AI-PFM (personal financial management) platform. -->

## Core Principles

### I. Mandatory Automated Testing
Every feature MUST ship with automated unit and integration tests, and the CI
suite MUST be green before merge. Integration tests MUST run against a real
Postgres provisioned via Testcontainers and migrated with Alembic (the service's
own DB); read-only access to backend tables MUST be exercised through fixtures or
mocks, never a live backend. All tests MUST be deterministic and mock-first for
the LLM: no test may issue a real model or external-network call, and mock
responses MUST match the production response shape exactly. Test-Driven
Development is encouraged but not mandated.

**Rationale**: Tests reaching live models or a live backend are slow,
non-deterministic, costly, and leak credentials into pipelines. A real-Postgres
integration layer catches schema and query defects that mocks hide, while
mock-first LLM tests keep the pipeline fast, free, and reproducible.

### II. Security & Secrets Discipline
This service is internal-only and MUST NEVER be exposed directly to the frontend;
it is invoked solely by the Django backend. Every Django-facing endpoint (any
route beyond liveness/readiness probes) MUST require a valid shared-secret Bearer
token. Secrets MUST NEVER be committed; CI MUST run both secret scanning and
dependency-vulnerability scanning and block on verified findings. Configuration
MUST fail fast at startup when a required secret is missing or set to a
placeholder value.

**Rationale**: The service processes sensitive financial data on behalf of a
banking backend. An exposed surface, leaked key, vulnerable dependency, or silent
misconfiguration is an unacceptable risk; failing loudly at boot always beats
serving in an insecure state.

### III. Data Protection & Compliance (NON-NEGOTIABLE)
Personally identifiable and financial data MUST be minimized and redacted before
it leaves a trust boundary — including before inclusion in logs and any
telemetry/observability export (e.g. an LLM tracing backend such as Langfuse).
Because backend mirror models expose FULL backend tables (see Principle IV), data
minimization MUST be enforced at the query/DTO **egress layer**, not the model
layer: queries MUST SELECT and project only the columns a feature needs, and
values MUST be mapped into purpose-scoped DTOs (with redaction) before crossing
any trust boundary. The mere presence of a column on a mirror model MUST NOT be
treated as license to read or egress it.

**Exception — live LLM inference only**: the model-inference request/response
itself is exempt from this minimization rule, but ONLY while the configured
model backend is self-hosted infrastructure under this organization's own
control. This exists because the service's core function — real financial
analysis and statement normalization — structurally requires full-fidelity
input to work at all, and a genuinely self-hosted call never leaves the
org's infrastructure. This exception is narrow and does NOT extend to any
secondary copy of that same content: logs, telemetry, and observability/
tracing exports (including everything captured by an LLM tracing backend)
remain fully subject to the unconditional minimization rule above — a trace
of an inference call is a second, persisted, more broadly-accessible copy of
that content and gets no exemption from the inference call it observes. The
exception is void the moment a non-self-hosted backend is configured (e.g.
`OPENAI_BASE_URL` / `EMBEDDING_BASE_URL` pointed at a real external vendor),
since Principle VI deliberately keeps the backend swappable via config alone
with no code change — this exception MUST NOT be read as a blanket allowance
for "LLM prompts" independent of where the model actually runs.

Every privileged action MUST be recorded to an audit log in the service's own
database. Data retention and data-residency rules MUST be defined and enforced;
data MUST NOT be retained longer than its stated purpose requires.

**Rationale**: This is regulated financial data. The service cannot deliver its
core function on redacted or pseudonymized input, so requiring prompt-level
redaction for a genuinely self-hosted model was unenforceable by design and
was, in practice, never real — no prompt-construction site in the codebase
performs redaction today. What full fidelity does NOT require is a second,
persisted copy of that content in a debugging/telemetry system, so the
minimization requirement stays absolute for logs and tracing exports. Tying
the inference exception to self-hosting, rather than granting it
unconditionally, matters because Principle VI keeps the model backend
swappable via config with no code change — an unconditional exception would
silently also cover a future external-vendor call. Generated full-table
mirrors are convenient but wide, so the minimization guarantee has to live
where data actually leaves the service — the query and DTO boundary — rather
than relying on a hand-curated column list. An immutable audit trail is a
baseline expectation for a financial system.

### IV. Data Ownership & Access Boundaries
The service uses two databases behind two separate SQLAlchemy `DeclarativeBase`
registries. The **own DB** is READ-WRITE and its metadata MUST be the *sole*
Alembic `target_metadata`. The **backend DB** is READ-ONLY BY DEFAULT: its Base
MUST be excluded from Alembic, and access MUST go through a dedicated
`ai_readonly` database role (DB-enforced). The application MUST treat the
backend DB as strictly read-only and MUST NOT write to it — UNLESS a write path
is both (a) backed by a narrowly-scoped DB-level GRANT already provisioned for
exactly that column or table, and (b) explicitly authorized for that specific
feature by a human, recorded in that feature's spec or PR. A write path MUST
NEVER be added speculatively, defensively, or "just in case" by a feature that
does not strictly need it — writing to the backend DB is something a feature
must be explicitly told to do, never something to reach for by default. Absent
both conditions, code MUST define no write paths against the backend DB.

The currently-authorized exceptions, matching the exact grants provisioned on
`ai_readonly`, are:
  - `transactions.embedding` — UPDATE only (this service computes and persists
    embeddings for existing backend transactions).
  - `monthly_summaries` — full CRUD (this service owns this table's lifecycle
    end-to-end).
Any additional write exception MUST be added to this list via a constitution
amendment before code may exercise it, and the code implementing an exception
MUST be scoped to exactly the columns/tables that exception's GRANT covers —
never broader. Where the role additionally restricts writes at the transaction
level (e.g. a `default_transaction_read_only = on` default), the required
per-transaction override (e.g. `SET TRANSACTION READ WRITE`) MUST be scoped to
the single transaction performing that authorized write, never applied to the
connection or session by default.

Own tables MUST live in the feature slice that owns them. Owned models MUST NOT
declare a real `ForeignKey` into a backend table; a cross-database reference MUST
be a logical, unconstrained `backend_*_id` column. The service MUST NEVER create,
alter, or drop backend-owned tables, and MUST NEVER write to one outside the
enumerated exceptions above; for everything else, it returns structured results
to Django, which persists them.

Backend tables MUST be represented as typed models in a shared module that are
**generated** directly from the read-only backend database via a pinned
code-generator (e.g. `sqlacodegen`), and MUST NEVER be hand-edited. Regeneration
is a manual developer step run against the live read-only backend; the generated
module is the sole committed artifact (there is no checked-in schema snapshot).
The generated module MUST carry a header marking it generated, and MUST bind its
models to the backend `DeclarativeBase` so the Alembic exclusion continues to
hold. Drift against the upstream schema is reconciled whenever a developer
regenerates and commits the module; no CI gate or scheduled job connects to the
backend database (CI stays offline, per Principle I).

**Rationale**: Two services writing one database corrupt each other's schema
unless ownership is explicit and enforced. A read-only-by-default role plus a
separate, Alembic-excluded Base makes the boundary impossible to cross by
accident rather than merely by convention. A small, enumerated,
explicitly-authorized exception list lets the two narrow write paths the
backend team has deliberately granted actually be used, while keeping every
other feature's default posture read-only — requiring both a DB-level grant
and human sign-off before any code exercises a write path prevents scope
creep, so a feature never grows a write path just because a column happens to
be writable in principle or "might be useful later." Hand-written mirrors
accumulate transcription error against an upstream schema this service does
not own; generating them directly from the backend eliminates that error by
construction. Regeneration is kept a manual, human-reviewed step so that CI
never depends on backend availability or credentials — the boundary is
verified offline by importing the committed module, not by reaching across
it.

### V. Feature-Bounded Modular Architecture
Code MUST be organized as feature-bounded vertical slices, each self-contained
(its own router, schemas, service, models, and tests). Package-by-layer
organization (top-level folders split by file type such as `routers/`,
`services/`, `repositories/`) is disallowed. Cross-feature interaction MUST go
through a feature's service interface, never by reaching into another slice's
repository or models.

**Rationale**: Layer-bounding forces edits across many folders for one change and
lets any layer reach into any other. Vertical slices maximize cohesion, make
boundaries enforceable, and let the service grow capability-by-capability as an
advisor rather than tangling as it scales.

### VI. LLM & Agent Architecture
The AI assistant MUST be implemented as a single Maestro orchestrator delegating
to purpose-built sub-agents on LangChain/LangGraph, with chat threads persisted
through LangChain's storage into the own DB. LLM access MUST go through
`langchain-openai` (`ChatOpenAI`) behind a configurable base URL and model name;
the model MUST NOT be hardcoded at a call site, preserving OpenAI/self-hosted
vLLM interchangeability. Dashboard analytics MUST be produced by background
pipeline jobs, not by agents on demand. Agent outputs MUST be guarded:
retrieval-grounded and sourced where applicable, never fabricating financial
figures, carrying appropriate advice disclaimers, and using PII-safe prompts.

**Rationale**: A single orchestration entry point keeps agent behavior auditable
and testable. Config-driven model selection avoids rewrites when cost, latency,
or data-residency change the backing provider. Serving dashboards from
pre-computed tables keeps the user-facing surface fast and deterministic;
guardrails keep financial advice safe and honest.

### VII. Operational Readiness & Fail-Fast Configuration
The service MUST expose liveness (`/health`) and readiness (`/ready`) probes that
require no auth and make no external calls, suitable for container healthchecks
and orchestrators. Configuration MUST be validated at import/startup time and
raise immediately on invalid or incomplete settings rather than deferring failure
to the first request.

**Rationale**: Container platforms depend on cheap, dependency-free probes to
route traffic safely. Validating configuration at boot turns latent runtime
failures into obvious startup failures.

### VIII. Library-First, Minimal Implementation
Code MUST prefer a well-maintained library or framework primitive over a
hand-rolled implementation whenever one already solves the problem well —
for example, structured LLM output via the provider SDK's native mechanism
rather than a hand-written regex-based JSON-rescue parser, or a real parser
rather than hand-rolled regex over structured markup (HTML tables and
similar). Implementations MUST stay clean and minimal: no speculative
abstractions, no new indirection layers introduced ahead of a real need, and
no reimplementing behavior a current dependency already provides well. Where
an existing pattern in the codebase already fits (e.g. a swappable-client
shape), reuse it deliberately rather than inventing a parallel one.

**Rationale**: Hand-rolled parsing and ad hoc client shapes duplicate logic
that well-tested libraries already solve more robustly, and each duplicate
becomes its own one-off maintenance burden. Preferring the library's native
mechanism keeps the codebase smaller and easier to reason about, and keeps
a pattern that already fits from being reinvented per feature instead of
intentionally reused.

## Technology & Quality Standards

- **Runtime**: Python 3.12, FastAPI, Pydantic v2 / pydantic-settings.
- **Async I/O**: `async def` routes with SQLAlchemy 2.0 async on `asyncpg`;
  `pytest-asyncio` for async tests. Own-DB schema managed by Alembic.
- **AI stack**: LangChain / LangGraph for the Maestro and sub-agents; LangChain
  storage for chat threads; `langchain-openai` for LLM access behind a
  configurable base URL/model.
- **Packaging**: `uv` with `pyproject.toml` and a committed `uv.lock` for
  reproducible dependency resolution (consolidating prior requirements files).
- **Formatting, linting & typing**: Code MUST pass Ruff (`E`, `F`, `I`), Black at
  line length 100, and `mypy`. Generated migration files are exempt from lint as
  configured; hand-written code is not.
- **Containerization**: The service MUST remain buildable as a self-contained
  container image and MUST expose a working `HEALTHCHECK`.

## Development Workflow & Quality Gates

- Changes MUST land via pull request; direct pushes to `main` for feature work
  are disallowed.
- CI is the merge gate. All of the following MUST pass before merge: Ruff lint,
  Black format check, `mypy`, the mock-mode unit tests, the Testcontainers
  integration tests, secret scanning, dependency-vulnerability scanning, and the
  container image build.
- Any change touching authentication, compliance/PII handling, data-access
  boundaries, or the LLM/agent layer MUST be explicitly reviewed against
  Principles II, III, IV, and VI in the PR discussion.

## Governance

This constitution supersedes ad-hoc practices for this repository. Amendments MUST
be proposed via pull request, documented in the Sync Impact Report at the top of
this file, and approved before merge. Versioning follows semantic versioning:
**MAJOR** for backward-incompatible governance or principle removals/
redefinitions, **MINOR** for a newly added principle or materially expanded
guidance, and **PATCH** for clarifications and non-semantic refinements. Every PR
and review MUST verify compliance with the principles above; unavoidable
deviations MUST be justified explicitly in the PR. Runtime development guidance
lives in repository docs and agent guidance files and MUST stay consistent with
this constitution.

**Version**: 2.3.0 | **Ratified**: 2026-07-09 | **Last Amended**: 2026-07-20
