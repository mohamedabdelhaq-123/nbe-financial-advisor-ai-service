# Implementation Plan: Normalizer Pipeline Rework

**Branch**: `016-normalizer-pipeline-rework` | **Date**: 2026-07-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/016-normalizer-pipeline-rework/spec.md`

## Summary

Rework the statement-normalization extraction pipeline (`app/features/ingestion/normalizer/`) so its
output actually matches the backend's transaction/account schema (a key-value map for extra facts
instead of a list of pairs; a real, unmasked account number; dedicated `balance`/
`merchant_normalized` fields), present source content to the model as clean per-type text instead of
JSON-wrapped HTML, replace the hand-rolled sequential/batch-tick extraction loop with LangGraph's
native `Send`-based fan-out and `max_concurrency`-bounded execution, size extraction chunks primarily
by estimated transaction-row count instead of raw character length, and split the package into a
shared-contract layer plus a per-strategy `agents/` subpackage so a second extraction strategy can be
added later without touching the first. Extraction call sites also gain business-context metadata
(statement, chunk, prompt version) on their `RunnableConfig` so this service's existing global
Langfuse auto-instrumentation produces traces that are actually useful for debugging and cost
tracking once execution is concurrent.

## Technical Context

**Language/Version**: Python 3.12 (existing service)

**Primary Dependencies**: No new dependencies. Reuses `langchain-openai`/LangGraph (native `Send`,
state reducers, `config={"max_concurrency": ...}`), `beautifulsoup4` (already used for table-row
splitting, now also driving markdown rendering), `jinja2` (existing prompt-template factory). The
existing global OTel/OpenInference auto-instrumentation (`app/core/observability.py`, spec 013)
requires no new package — this feature only adds `RunnableConfig` metadata at the call site.

**Storage**: No new storage. Same object-storage bucket/prefix convention (`{bucket}/{statement_id}/
normalized.json`) and own-DB `categories`/audit tables as the existing normalization feature (spec
005); no schema/migration change.

**Testing**: `pytest`, mock-first (Constitution I). New/changed unit tests cover: row-count-primary
chunking, the content_list→markdown renderer (one case per entry type), the extra_fields list→dict
conversion at the service boundary, `account_number`/`balance`/`merchant_normalized` passthrough, the
`Send`/reducer graph producing identical output to a fully-sequential run (FR-009), all-or-nothing
failure propagation when one portion exhausts retries (FR-016), and that `RunnableConfig` metadata is
attached at the extraction call site (asserted via a stub `Runnable` capturing the config it
receives — no real model or Langfuse call).

**Target Platform**: Linux containers via Docker Compose (unchanged).

**Project Type**: Existing single-project FastAPI service. This feature restructures one existing
feature-slice subpackage (`app/features/ingestion/normalizer/`) into a shared-contract layer plus a
per-strategy `agents/` subpackage; no new top-level project or service boundary.

**Performance Goals**: SC-003 — a 3+ page / 40+ transaction statement (this codebase's existing
real-world validation benchmark, research.md §9 of spec 005) completes at least 2x faster with a
raised concurrency limit than fully sequential. SC-004 — zero truncated/incomplete portions at that
same size, across repeated runs.

**Constraints**: FR-016 — all-or-nothing failure must survive the move to concurrent execution (no
silent partial-result mode). FR-011 — the output-shape change is a breaking contract change requiring
a coordinated backend-side update; this plan's tasks are scoped to the AI service only, and the
backend-side coordination is a process dependency tracked outside this repo, not a code deliverable
here. FR-013 — prompt-version identification must stay additive to the existing git-committed Jinja2
templates, not migrate prompt storage into Langfuse's own hosted prompt management. The Clarifications
session explicitly deferred extending telemetry redaction to cover the new unmasked account number —
that gap is out of scope for this feature and must be tracked, not silently dropped.

**Scale/Scope**: `app/features/ingestion/normalizer/` and its new `agents/chunked_langgraph/`
subpackage, `app/features/ingestion/service/normalize.py`, and `app/core/config.py` (two new
settings). No other feature slice is touched.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design below.*

| Principle | Assessment |
|---|---|
| I. Mandatory Automated Testing | **PASS.** Every new/changed behavior (row-count chunking, markdown rendering, dict-shaped extra_fields, `Send`/reducer graph parity with sequential execution, all-or-nothing failure, config metadata attachment) is unit-testable against the existing mock-first LLM convention — no test needs a real model or a real Langfuse endpoint. |
| II. Security & Secrets Discipline | **PASS.** No new secrets or external endpoints introduced. |
| III. Data Protection & Compliance (NON-NEGOTIABLE) | **CONDITIONAL PASS — explicit tracked exception.** FR-002 puts a real, unmasked account number into the model's input/output. That call itself is covered by Principle III's self-hosted-inference exception, but the *same content will also reach this service's existing global auto-instrumentation and be exported to Langfuse as telemetry* — a secondary copy the amended Principle III does **not** exempt. Today's `RedactionSpanProcessor` (spec 013) only recognizes card/phone/email shapes, not bank account numbers, so this is a real, currently-unmitigated gap. The Clarifications session (2026-07-23) explicitly decided this is out of scope for this feature and must be tracked as a separate, later follow-up rather than silently shipped unaddressed — **tasks.md MUST include a visible tracking item (e.g. a code `TODO` referencing this plan, plus a follow-up backlog entry) so this isn't lost**, and the PR description must call it out per the constitution's "unavoidable deviations MUST be justified explicitly in the PR" governance clause. |
| IV. Data Ownership & Access Boundaries | **PASS / not applicable.** No backend-DB write path of any kind; `categories`/audit reads-and-writes stay exactly as spec 005 established. |
| V. Feature-Bounded Modular Architecture | **PASS.** The `normalizer/agents/<strategy>/` split stays entirely inside the `ingestion` slice — it's a deeper application of this same principle (vertical-slice cohesion), not a new cross-slice boundary. |
| VI. LLM & Agent Architecture | **PASS.** Model access still goes exclusively through `get_chat_model()`; no model name is hardcoded at a call site; still LangGraph-based. |
| VII. Operational Readiness & Fail-Fast Configuration | **PASS, with new validators.** Two new settings (`normalizer_strategy`, `normalization_est_tokens_per_row`) need fail-fast validation: `normalizer_strategy` is typed as a `Literal` (invalid values are a Pydantic parse-time failure, not a runtime one); `normalization_est_tokens_per_row` gets a `Field(gt=0)` constraint so a zero/negative value can't silently produce a zero-row chunk cap. |
| VIII. Library-First, Minimal Implementation | **PASS.** Replacing the hand-rolled batch-tick `asyncio.gather` self-loop with LangGraph's native `Send` fan-out, state reducers, and `config={"max_concurrency": ...}` is a direct instance of this principle — verified against the installed package source (`langgraph/pregel/_executor.py`), not assumed. The markdown renderer continues using BeautifulSoup (already a dependency) rather than hand-rolled regex over HTML. |

No violations requiring justification in Complexity Tracking, aside from the tracked Principle III
exception above (explicit, time-bound, requester-approved — not a silent gap).

## Project Structure

### Documentation (this feature)

```text
specs/016-normalizer-pipeline-rework/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
└── tasks.md              # Phase 2 output (/speckit.tasks command — not created by this command)
```

### Source Code (repository root)

```text
app/features/ingestion/
├── categories.py                        # unchanged
├── router.py                             # unchanged
├── schemas.py                             # unchanged (API request/response contract untouched — only
│                                           #   normalized_json's internal shape changes)
├── normalizer/
│   ├── __init__.py                        # edited: get_normalizer_client() dispatches on
│   │                                       #   settings.chat_model.normalizer_strategy instead of a
│   │                                       #   bare mock/real bool branch
│   ├── schemas.py                          # edited: NormalizerClient.normalize() gains statement_id/
│   │                                       #   ocr_result_id kwargs (FR-012); ExtractedStatement.
│   │                                       #   account_number replaces account_hint (FR-002);
│   │                                       #   ExtractedTransaction gains balance, merchant_normalized
│   │                                       #   (FR-003) — ExtraField/list-of-pairs shape unchanged
│   │                                       #   here (still the strict-mode-compatible LLM contract)
│   ├── mock.py                             # edited: mirrors the new field names/shape
│   ├── duplicates.py                        # unchanged
│   └── agents/
│       └── chunked_langgraph/
│           ├── __init__.py
│           ├── graph.py                     # rewritten: Send-based fan-out + reducers +
│           │                                #   config={"max_concurrency": ...} replacing the
│           │                                #   batch-tick self-loop node; per-call RunnableConfig
│           │                                #   metadata/tags (statement_id, ocr_result_id,
│           │                                #   chunk_index, prompt_version) (FR-012, FR-015)
│           ├── chunking.py                  # rewritten: row-count-primary portioning for table
│           │                                #   entries (FR-007), fallback char ceiling (FR-008),
│           │                                #   liberal packing for non-table entries
│           ├── markdown_render.py            # new: content_list entry → clean text/markdown,
│           │                                #   one branch per entry type (FR-004)
│           ├── prompts.py                    # moved from normalizer/prompts.py; adds a
│           │                                #   content-hash prompt_version identifier (FR-013)
│           └── prompt_templates/
│               └── normalization.jinja2       # moved, unchanged content
├── service/
│   ├── normalize.py                         # edited: extra_fields list→dict conversion at the
│   │                                        #   response/storage boundary (FR-001); account_number
│   │                                        #   passthrough (FR-002); balance/merchant_normalized
│   │                                        #   passthrough (FR-003); passes statement_id/
│   │                                        #   ocr_result_id into normalize() (FR-012)
│   └── process.py                            # unchanged

app/core/config.py                           # edited: normalizer_strategy: Literal["chunked_langgraph"]
                                              #   (FR-010); normalization_est_tokens_per_row: int
                                              #   (drives the FR-007 row-cap formula)

tests/features/ingestion/
├── test_normalizer.py                        # edited: chunking/graph tests updated for new module
│                                             #   paths and row-count-based behavior
└── test_service.py                            # edited: extra_fields dict shape, account_number,
                                              #   balance/merchant_normalized assertions
```

**Structure Decision**: Existing single-project FastAPI service; no new project or slice boundary.
Within the existing `ingestion` slice, `normalizer/` splits into a shared-contract layer (`schemas.py`
Protocol + `Extracted*` models, `mock.py`, `duplicates.py` — strategy-agnostic, usable regardless of
which extraction strategy is active) and a new `agents/chunked_langgraph/` subpackage holding
everything specific to today's one real strategy (graph, chunking, markdown rendering, prompt +
template). This directly answers User Story 5/FR-010: adding a second strategy later means adding a
sibling `agents/<name>/` subpackage and one new branch in `get_normalizer_client()`, never touching
the first strategy's files.

## Post-Design Constitution Check

*Re-checked after Phase 1 (data-model.md, contracts/, quickstart.md).*

No new violations introduced by the design artifacts. Confirms: the `Send`/reducer graph design
(research.md §6) is verified against the installed `langgraph` package source, not assumed from
memory or docs alone (Principle VIII); the Principle III exception remains exactly as scoped in the
Constitution Check above — data-model.md's `NormalizerClient.normalize()` signature change threads
`statement_id`/`ocr_result_id` through for FR-012's business-context tagging, which is precisely the
content that widens the existing telemetry-redaction gap, so quickstart.md's validation steps
explicitly re-surface the tracked exception rather than letting it disappear once observability
"looks like it's working." No backend-DB interaction is introduced anywhere in the design (Principle
IV stays not-applicable). Gate remains **CONDITIONAL PASS** on the same tracked, requester-approved
Principle III exception.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|---------------------------------------|
| Telemetry redaction gap for account numbers left unmitigated (Principle III) | Requester explicitly scoped this out of the feature during `/speckit-clarify` (2026-07-23) to keep this feature's delivery unblocked | Extending redaction now was considered (Clarifications Q1, option A) and rejected by the requester in favor of tracking it separately — not rejected for technical reasons, so no alternative implementation is being weighed here; the item is deferred, not solved differently |
