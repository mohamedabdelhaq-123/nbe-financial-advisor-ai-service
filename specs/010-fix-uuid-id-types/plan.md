# Implementation Plan: UUID Identifier Consistency

**Branch**: `010-fix-uuid-id-types` | **Date**: 2026-07-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-fix-uuid-id-types/spec.md`

## Summary

The AI service mistypes two backend-owned identifiers — `user_id` and `product_id` — as integers across its request contracts, its own persisted tables, its audit log, and its widget payloads, even though the Django backend keys `Users`, `Products`, and every foreign key into them by UUID. The fix is end-to-end UUID consistency: every surface on this service that holds or carries either identifier is changed to UUID, the audit attribution path and the analysis-agent query lose their `int()`/`str()` coercions, the recommendation agent reads the real product title from the backend `Products` table (replacing the fabricated `"Product {id}"` placeholder), and the misleading integer-like examples in the analytics contract are swept to realistic UUID strings. The not-yet-deployed own-DB migration is amended in place rather than augmented with a corrective migration.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, Pydantic v2 / pydantic-settings, SQLAlchemy 2.0 async (asyncpg), Alembic, pgvector, LangChain / LangGraph, langchain-openai. (No new dependencies introduced.)

**Storage**: PostgreSQL — two databases. Own DB (read-write, Alembic-managed) holds the audit log and the recommendation tables whose column types change. Backend DB (read-only `ai_readonly` role) holds `Users`, `Products`, `Transactions`, etc., whose UUID types are the ground truth being aligned to.

**Testing**: `pytest` + `pytest-asyncio`; mock-first for LLM paths; Testcontainers-backed real-Postgres integration tests against the own DB; read-only backend access exercised through mocks/fixtures (never live in CI). The full suite must stay green.

**Target Platform**: Linux server, containerized (self-contained image with `HEALTHCHECK`).

**Project Type**: web-service (internal FastAPI service invoked solely by the Django backend over a shared-secret Bearer token).

**Performance Goals**: The hot path is the chat SSE stream. The identifier-type changes are zero-cost at runtime (UUIDs and integers are the same size at the wire layer; native UUID columns are equally fast to index). The one new runtime cost is a single backend `Products` lookup per recommendation turn — bounded to `top_k ≤ 3` rows, fetched via the existing read-only session pattern already used by the analysis agent. Acceptable.

**Constraints**: Internal-only service (never frontend-facing). Constitution-governed: fail-fast config validation, mock-first tests, read-only backend by default, every privileged action audited. No new dependencies, no new write paths to the backend DB.

**Scale/Scope**: Cross-cutting fix touching 5 features (`chat`, `audit`, `recommendations`, `transactions` only as a mypy ripple, `analytics` examples only). ~14 source files, 1 migration file, ~8 test files, 3 spec/contract artifacts amended.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| **I. Mandatory Automated Testing** | Every touched identifier surface has its tests updated to UUID values; both mock-mode unit and Testcontainers real-Postgres integration tests must pass. New: a real-Postgres test asserting the amended migration produces UUID-typed columns natively. | PASS — FR-012, SC-005 encode this. |
| **II. Security & Secrets Discipline** | No change to auth or secrets. The shared-secret Bearer gate (`require_token`) is untouched; only the typed body it admits changes. | PASS — out of scope, intentionally. |
| **III. Data Protection & Compliance (NON-NEGOTIABLE)** | This feature **exists to satisfy** Principle III: today's integer-typed audit column cannot reliably attribute a privileged chat turn to a real user. After this fix, every audit row carries the backend's UUID unchanged, and every request carrying a non-UUID identifier is rejected at the Pydantic boundary before any privileged action or audit write runs. | PASS — FR-001, FR-003, FR-004, SC-001, SC-003 directly encode the compliance posture. |
| **IV. Data Ownership & Access Boundaries** | (a) The own-DB column type changes are inside this service's Alembic-managed boundary — no impact. (b) The new `Products` read goes through the existing `get_backend_session()` read-only dependency already used by the analysis agent — no new write path, no new grant, no scope creep. (c) The migration is amended (not appended) only because it has not been deployed with real data; this is a one-time allowed deviation from the typical "append-only migration history" practice and is recorded in the assumptions. | PASS — FR-007, FR-009, Assumptions, and the no-new-write-path invariant all encode this. |
| **V. Feature-Bounded Modular Architecture** | The new `Products` read for the product title goes **through the recommendations service interface** (`match()`), not by having the chat agent reach into the backend `Products` model directly. The recommendations service is the only place that owns product reads, preserving slice boundaries. | PASS — FR-007 and the research.md design decision encode this. |
| **VI. LLM & Agent Architecture** | No change to the Maestro/sub-agent architecture, the LangGraph pipeline, or the checkpointer. The agent-internal changes are pure type cleanup (drop a cast, swap a fabricated name for a fetched one). | PASS — out of architectural scope, intentionally. |
| **VII. Operational Readiness & Fail-Fast Configuration** | Pydantic rejects non-UUID identifiers at request validation time, surfacing as a 422 before the stream starts — consistent with the fail-fast posture. No new config or probes. | PASS — FR-001 encodes this. |
| **VIII. Library-First, Minimal Implementation** | Uses the stdlib `uuid.UUID` type, SQLAlchemy's native `Uuid` column type (SA 2.0+), and Pydantic's `UUID4` annotation — no hand-rolled UUID handling, no new abstraction. *(Revised 2026-07-15: a `UserContext` model was introduced then removed the same cycle — research.md D11 — once it became clear `user_id` belongs solely on the request root, not duplicated inside `initial_context`. The final shape adds no new model at all: `initial_context` stays a plain `dict`, and identity flows through `ChatTurnRequest.user_id` → `ConversationState.user_id` directly.)* | PASS — no speculative abstraction introduced; D11 removed one instead of adding it. |

**Gate verdict (Phase 0)**: PASS. Proceeding to Phase 0 research.

### Post-design re-check (after Phase 1)

Re-evaluated against the design decisions in `research.md` (D1–D10) and the artifact contents:

| Principle | Post-design verdict |
|---|---|
| **I. Mandatory Testing** | PASS — `quickstart.md` Step 6 names the new Testcontainers test asserting the four amended columns are `Uuid`-typed; FR-012 + SC-005 unchanged. |
| **III. Data Protection** | PASS — `data-model.md` confirms `AiAuditLog.user_id` is `Uuid` natively; `quickstart.md` Step 3 verifies non-UUID `user_id` is rejected at 422 before any audit write. |
| **IV. Data Ownership** | PASS — `research.md` D2 records the in-place migration amendment as a one-time allowed deviation (not deployed with data); D4 + D10 confirm the new `Products` read goes through the existing read-only `get_backend_session()` with no new write path and no new grant. |
| **V. Feature-Bounded** | PASS — D4 places the product-title fetch inside `recommendations.service.match()`, not in the chat agent. Slice boundary preserved. |
| **VIII. Library-First** | PASS — D1 uses stdlib `uuid.UUID` + SA native `Uuid` + Pydantic `UUID4`; no hand-rolled UUID handling, no new abstraction, no new dependency. |

All other principles (II, VI, VII) were PASS at Phase 0 and nothing in the design touches them.

**Gate verdict (Phase 1)**: PASS. All artifacts ready; feature is plannable into tasks via `/speckit.tasks`.

## Project Structure

### Documentation (this feature)

```text
specs/010-fix-uuid-id-types/
├── plan.md                          # This file
├── spec.md                          # /speckit.specify output
├── research.md                      # Phase 0 output — design decisions consolidated
├── data-model.md                    # Phase 1 output — entity/table/DTO shapes
├── quickstart.md                    # Phase 1 output — runnable end-to-end validation
├── checklists/
│   └── requirements.md              # /speckit.specify output
└── contracts/
    ├── chat-stream-amendment.md     # Phase 1 — breaking change to widget product_id
    ├── recommendations-match.md     # Phase 1 — establishes the standalone match contract
    └── chat-request-amendment.md    # Post-implementation — is_first_turn removal, initial_context reshape (D11)
```

### Source Code (repository root)

```text
app/
├── core/
│   ├── audit.py                     # AMEND record_audit signature: user_id int -> UUID
│   └── ...
├── features/
│   ├── audit/models.py              # AMEND AiAuditLog.user_id: Integer -> Uuid
│   ├── chat/
│   │   ├── schemas/
│   │   │   ├── request.py           # AMEND ChatTurnRequest.user_id -> UUID4; is_first_turn removed; initial_context stays dict (D11)
│   │   │   └── widgets.py           # AMEND ProductMatchPayloadItem.product_id: str -> UUID4
│   │   ├── state.py                 # AMEND ConversationState gains root-level user_id: uuid.UUID (D11)
│   │   ├── service.py               # AMEND audit call uses UUID; unconditional aget_state restore replaces is_first_turn gating (D11)
│   │   └── agents/
│   │       ├── analysis.py          # AMEND drop str(user_id) coercion; read user_id from state["user_id"] (D11)
│   │       └── recommendation.py    # AMEND drop int() and str() casts; user_id from state["user_id"] (D11)
│   ├── recommendations/
│   │   ├── schemas.py               # AMEND MatchRequest.user_id, ProductMatch.product_id -> UUID4
│   │   ├── models.py                # AMEND AiProblemStatement.product_id, AiRecommendationLog.{user,product}_id -> Uuid
│   │   ├── service.py               # AMEND match() signature + fetch real product title from backend Products
│   │   └── seed.py                  # AMEND documented JSON input format: product_id as UUID string
│   └── analytics/
│       └── schemas.py               # AMEND examples only (no type change): "1001"/"5001" -> UUID strings
└── backend_db/                       # UNCHANGED — already correctly UUID-typed (the ground truth)

migrations/versions/
└── a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py   # AMEND 4x sa.Integer() -> sa.Uuid()

tests/
├── features/
│   ├── chat/
│   │   ├── test_chat.py             # AMEND request factory: user_id int -> UUID4
│   │   ├── test_streaming.py        # AMEND request factory: user_id int -> UUID4; drop is_first_turn kwarg (D11)
│   │   ├── test_schemas.py          # AMEND product_id examples: "1" -> UUID string; add non-UUID rejection test
│   │   ├── test_analysis_agent.py   # AMEND state dict: root-level user_id, no UserContext (D11)
│   │   └── test_recommendation_integration.py  # AMEND product_id values + assertion; root-level user_id (D11)
│   └── recommendations/
│       ├── test_recommendations.py  # AMEND product_id values + assertions
│       └── test_seed.py             # AMEND product_id values
└── integration/
    ├── test_migrations.py           # AMEND add UUID column-type assertion after alembic upgrade head
    └── test_chat_memory.py          # AMEND state dict: root-level user_id, no UserContext (D11)
```

**Structure Decision**: Single-project (the existing layout). This is a cross-cutting type-consistency fix that touches multiple feature slices; no new feature slice is created. The one cross-slice call (chat → recommendations for product titles) is routed through the existing `recommendations.service.match()` interface per Principle V — the chat agent never reaches into the backend `Products` model directly.
