# Implementation Plan: LLM Observability with Langfuse

**Branch**: `013-langfuse-observability` | **Date**: 2026-07-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/013-langfuse-observability/spec.md`

## Summary

Capture end-to-end traces of every LLM call made by the service (chat agents, statement normalization, planning, embeddings) using a self-hosted, OpenTelemetry-based auto-instrumentation layer, and run the observability backend (Langfuse v3) as part of this repo's own Docker Compose stack. Integration is a single process-wide instrumentation call at startup — `LangChainInstrumentor().instrument()` exporting via OTLP to Langfuse — with no changes to individual LLM call sites, paired with span-level redaction to satisfy the service's data-minimization requirements, and built to fail open so a down/unreachable Langfuse never affects a user-facing request.

## Technical Context

**Language/Version**: Python 3.12 (existing service)

**Primary Dependencies**: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `openinference-instrumentation-langchain` (new); existing `langchain-openai`/LangGraph stack is instrumented, not modified.

**Storage**: Two new storage systems, both owned entirely by Langfuse and never touched directly by this service's code: Langfuse's own Postgres (transactional metadata) and ClickHouse (trace/observation analytics), plus Redis (job queue) and MinIO (S3-compatible blob storage for raw events). None of these are part of the AI service's own Alembic-managed database — no new tables, no new `DeclarativeBase` models.

**Testing**: `pytest` (existing suite). New unit tests cover `configure()`'s no-crash behavior and the redaction span processor's attribute-stripping, entirely in-process — no test starts a real Langfuse/ClickHouse container or makes a real OTLP network call, per Constitution Principle I.

**Target Platform**: Linux containers via Docker Compose (existing deployment shape for this repo).

**Project Type**: Existing single-project FastAPI service; this feature adds one new cross-cutting core module plus a vendored sub-stack of infrastructure containers — no new "project" in the repo-structure sense.

**Performance Goals**: Trace visibility within 10s of request completion (SC-001); span export must add no measurable latency to the request path (async/batched export, off the request path).

**Constraints**: Must fail open — an unreachable/slow Langfuse must never block or error a user-facing request (FR-005, SC-004). Must pattern-redact sensitive span content before OTLP export to Langfuse — this feature carries Principle III's minimization rule at full strength even though the self-hosted LLM call it observes does not (Constitution Principle III v2.3.0; research.md §3). Observability config must be optional — absent Langfuse settings disable tracing rather than failing startup (research.md §6).

**Scale/Scope**: Local/dev Docker Compose stack only, per spec Assumptions; multi-environment (staging/prod) topology is explicitly out of scope for this feature.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design below.*

| Principle | Assessment |
|---|---|
| I. Mandatory Automated Testing | **PASS.** New tests are in-process/mock-first (span construction + attribute assertions), no real Langfuse/OTLP network call, matching the existing mock-first-for-external-calls rule. |
| II. Security & Secrets Discipline | **PASS.** `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` follow the existing `.env`-based, gitignored secret pattern (same as `OPENAI_API_KEY`). Langfuse's own UI requires its own login (NextAuth-backed); its `NEXTAUTH_SECRET`/`ENCRYPTION_KEY`/`SALT` are generated secrets, never committed, following the same pattern. |
| III. Data Protection & Compliance (NON-NEGOTIABLE) | **PASS, with a mandatory design element.** As of v2.3.0, Principle III exempts only the *live, self-hosted LLM inference call* from redaction — an exported trace is explicitly named as a secondary copy that stays fully subject to minimization. Addressed by pairing the instrumentor with a required, pattern-level redaction `SpanProcessor` (research.md §3) — not `OPENINFERENCE_HIDE_*` whole-attribute hiding, which would satisfy the letter of the rule by deleting the trace's usefulness (conflicting with FR-001/US1's "inputs and outputs visible"). Required scope, not optional hardening. |
| IV. Data Ownership & Access Boundaries | **PASS / not applicable.** Langfuse's Postgres/ClickHouse are fully separate systems this service never queries or writes to directly; no backend-DB interaction of any kind. |
| V. Feature-Bounded Modular Architecture | **PASS.** New code lives in `app/core/observability.py`, a cross-cutting core module — same placement precedent as `app/core/logging.py`, not a feature slice. |
| VI. LLM & Agent Architecture | **PASS.** No change to `ChatOpenAI`, the Maestro orchestrator, or any sub-agent; the model is never hardcoded, and this feature doesn't touch that call path at all — it observes it from outside. |
| VII. Operational Readiness & Fail-Fast Configuration | **PASS, with a scoped exception.** Langfuse settings are intentionally optional and do not participate in fail-fast validation — absent config disables tracing rather than raising at boot, which is required by FR-005's fail-open mandate and does not weaken fail-fast behavior for any *required* setting. |
| VIII. Library-First, Minimal Implementation | **PASS, with one deliberate exception.** Instrumentation and export use well-maintained OTel/OpenInference libraries with no hand-rolled span creation. Redaction is the one hand-rolled piece — OpenInference's built-in `OPENINFERENCE_HIDE_*` mechanism was evaluated and rejected (research.md §3) because it's whole-attribute-only and doesn't solve *this* problem well (it can't preserve visibility while stripping PII patterns), so a small custom `SpanProcessor` is justified rather than forced into a library primitive that doesn't fit. |

No violations requiring justification in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/013-langfuse-observability/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command — not created by this command)
```

### Source Code (repository root)

```text
compose/
├── docker-compose.yml           # edited: `include:` the new langfuse sub-stack
├── docker-compose.dev.yml       # unchanged unless local port/network overrides are needed
└── langfuse/
    └── docker-compose.yml       # new: langfuse-web, langfuse-worker, postgres, clickhouse, redis, minio

app/
├── core/
│   ├── config.py                 # edited: new optional langfuse_host/public_key/secret_key settings
│   ├── logging.py                # unchanged — existing configure() precedent this feature follows
│   ├── observability.py          # new: configure() — TracerProvider + OTLP exporter + LangChainInstrumentor + redaction/attribution processor
│   ├── request_logging.py        # edited: also bind a `current_feature` ContextVar from the request path (research.md §7), alongside the existing correlation-ID binding
│   └── llm.py                    # unchanged — auto-instrumentation observes it, doesn't modify it
└── main.py                       # edited: call app_observability.configure() alongside app_logging.configure()

tests/
└── core/
    └── test_observability.py     # new: configure() no-crash behavior, redaction processor unit tests

.env.example                      # edited: new LANGFUSE_* / observability-related vars, documented
pyproject.toml                    # edited: opentelemetry-sdk, opentelemetry-exporter-otlp-proto-http,
                                   #         openinference-instrumentation-langchain
```

**Structure Decision**: Single existing project (FastAPI service) — this feature adds one new cross-cutting `app/core/observability.py` module (mirroring the existing `app/core/logging.py` initialization pattern) plus a vendored, self-contained infrastructure sub-stack under `compose/langfuse/`, pulled into the main Compose project via `include:`. No feature-slice code is added; no new project/package boundary is introduced.

## Post-Design Constitution Check

*Re-checked after Phase 1 (data-model.md, contracts/, quickstart.md).*

No new violations introduced by the design artifacts. Confirms: no tables/models added to the AI service's own database (data-model.md) — Principle IV stays not-applicable; the redaction requirement from Principle III is carried through as a first-class contract item (contracts/observability-config.md §1, quickstart.md step 3) rather than left implicit; secret handling for both `LANGFUSE_*` app config and Langfuse's own first-run secrets follows the existing `.env`/gitignored pattern (contracts §1, quickstart step 2); fail-open behavior has an explicit, executable validation step (quickstart step 5). Gate remains **PASS**.

## Complexity Tracking

*No Constitution Check violations — this section is not applicable.*
