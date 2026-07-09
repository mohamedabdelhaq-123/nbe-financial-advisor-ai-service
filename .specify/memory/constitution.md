<!--
SYNC IMPACT REPORT
==================
Version change: (template, unversioned) → 1.0.0
Rationale: Initial ratification. First concrete constitution replacing the
unfilled template; MAJOR baseline established for the FastAPI AI service of the
AI-PFM system.

Principle mapping (template slot → ratified principle):
  - [PRINCIPLE_1_NAME] → I. Mandatory Automated Testing
  - [PRINCIPLE_2_NAME] → II. Security & Secrets Discipline
  - [PRINCIPLE_3_NAME] → III. Data Protection & Compliance (NON-NEGOTIABLE)
  - [PRINCIPLE_4_NAME] → IV. Data Ownership & Access Boundaries
  - [PRINCIPLE_5_NAME] → V. Feature-Bounded Modular Architecture
  - (added)           → VI. LLM & Agent Architecture
  - (added)           → VII. Operational Readiness & Fail-Fast Configuration

Added sections:
  - Technology & Quality Standards (was [SECTION_2_NAME])
  - Development Workflow & Quality Gates (was [SECTION_3_NAME])

Removed sections: none

Templates checked for consistency:
  ✅ .specify/templates/plan-template.md — Constitution Check gate is generic and
     aligns; no principle-specific edits required.
  ✅ .specify/templates/spec-template.md — no mandatory-section conflicts.
  ✅ .specify/templates/tasks-template.md — testing/data/agent task categories
     consistent with Principles I, IV, and VI.
  ✅ .specify/templates/checklist-template.md — no conflicts.

Follow-up TODOs: none. Ratification date set to initial adoption date.
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
it leaves a trust boundary — including before inclusion in LLM prompts and logs.
Every privileged action MUST be recorded to an audit log in the service's own
database. Data retention and data-residency rules MUST be defined and enforced;
data MUST NOT be retained longer than its stated purpose requires.

**Rationale**: This is regulated financial data. PII exposure through prompts,
logs, or over-retention creates compliance and reputational liability that no
feature benefit can justify. An immutable audit trail is a baseline expectation
for a financial system.

### IV. Data Ownership & Access Boundaries
The service uses two databases behind two separate SQLAlchemy `DeclarativeBase`
registries. The **own DB** is READ-WRITE and its metadata MUST be the *sole*
Alembic `target_metadata`. The **backend DB** is READ-ONLY: its Base MUST be
excluded from Alembic, access MUST go through a dedicated read-only database role
(DB-enforced), and the application MUST define no write paths against it. Backend
tables MUST be represented as hand-written typed models in a shared module; own
tables MUST live in the feature slice that owns them. The service MUST NEVER
create, alter, drop, or write backend-owned tables; it returns structured results
to Django, which persists them.

**Rationale**: Two services writing one database corrupt each other's schema
unless ownership is explicit and enforced. A read-only role plus a separate,
Alembic-excluded Base makes the boundary impossible to cross by accident rather
than merely by convention.

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

**Version**: 1.0.0 | **Ratified**: 2026-07-09 | **Last Amended**: 2026-07-09
