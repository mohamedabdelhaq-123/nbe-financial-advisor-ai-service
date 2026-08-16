# Implementation Plan: Templated Prompt Management

**Branch**: `015-jinja-prompt-templates` | **Date**: 2026-07-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/015-jinja-prompt-templates/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Externalize the five currently hardcoded, inline-string prompts (statement-normalization
extraction, chat conversation-summarization, chat intent-classification, chat
grounded-analysis, budget-allocation) into Jinja2 template files stored in a
`prompt_templates/` subdirectory scoped to each owning feature. A single shared factory,
`build_prompts_env()` in `app/core/jinja.py`, builds a strict, non-autoescaping,
`FileSystemLoader`-backed `Environment` rooted at a given feature's template directory.
Each feature gets a `prompts.py` module that builds its `Environment` once at import time
(module-level singleton — satisfies the "load once, reuse" requirement without extra
caching machinery) and exposes small, zero-argument helper functions (e.g.
`get_normalization_prompt() -> Template`) that locate and return the `jinja2.Template`
object — callers then call `.render(...)` themselves with that prompt's specific
inputs, exactly as they assemble those inputs today. This is a mechanical refactor:
wording and structure are preserved byte-for-byte; only *where* the text lives and
*how it's located* changes — input plumbing stays with the caller.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Jinja2 (new direct dependency — not currently installed;
confirmed absent via `import jinja2` failing), FastAPI, LangChain/LangGraph,
`langchain-openai`, pydantic-settings

**Storage**: N/A — prompt templates are plain-text files shipped alongside their
feature's source (no database, no packaging step; the Docker image does `COPY . .`
so template files travel with the code in both dev and prod images)

**Testing**: pytest, pytest-asyncio (existing suite conventions — mock-first for the
LLM per Constitution I; template rendering itself is pure Python/Jinja and needs no
model or DB access)

**Target Platform**: Linux server (containerized FastAPI service)

**Project Type**: Single project, feature-bounded vertical slices (existing `app/features/*`
layout)

**Performance Goals**: N/A beyond "no regression" — template compilation is cached per
feature at import time (FR-007), so steady-state rendering cost is a single Jinja
`Template.render()` call, negligible next to the LLM call it feeds.

**Constraints**:
- Rendering MUST use `jinja2.StrictUndefined` so a missing required variable raises
  immediately (FR-004) rather than silently rendering blank/default text.
- Autoescaping MUST be off — output is plain text sent to a model, not HTML (FR-006).
- Rendered output MUST be byte-for-byte identical to today's hardcoded prompt for the
  same inputs (FR-005) — verified per template with a golden-string test.

**Scale/Scope**: 1 shared core factory + 3 feature slices touched
(`ingestion/normalizer`, `chat`, `plan`) + 5 template files + 3 `prompts.py` modules.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Mandatory Automated Testing** — PASS. New behavior (template loading/rendering,
  helper functions) is pure Python/Jinja with no LLM or DB dependency, so it's trivially
  unit-testable without mocks. Existing tests that exercise these code paths via a fake
  `ainvoke` stub must keep passing unmodified (none currently assert on literal prompt
  strings — confirmed by inspection of `test_normalizer.py`, `test_maestro.py`,
  `test_streaming.py`, `test_planner_integration.py`), satisfying SC-003. New tests will
  assert golden-string equality against the current hardcoded output, per FR-005.
- **II. Security & Secrets Discipline** — N/A. No secrets, endpoints, or auth surface
  touched.
- **III. Data Protection & Compliance** — N/A / no change. This refactor changes *where*
  prompt wording is stored, not what data flows into a prompt or how it's redacted;
  today's redaction posture (or lack thereof, per the constitution's own Sync Impact
  Report) is unchanged either way.
- **IV. Data Ownership & Access Boundaries** — N/A. No database access added.
- **V. Feature-Bounded Modular Architecture** — PASS by design. Each feature's
  `prompt_templates/` + `prompts.py` lives inside that feature's own vertical slice
  (`app/features/ingestion/normalizer/`, `app/features/chat/`, `app/features/plan/`);
  the one cross-cutting piece, `build_prompts_env()`, goes in `app/core/`, mirroring
  existing shared core modules (`config.py`, `llm.py`) exactly as the spec's own
  Assumptions section directs. No feature reaches into another feature's template
  directory.
- **VI. LLM & Agent Architecture** — N/A / no change. Model access still goes through
  `get_chat_model()` / `ChatOpenAI` unchanged; this refactor only changes how the prompt
  *string* passed to that call is constructed. Guardrail behavior (disclaimers,
  grounding) is untouched.
- **VII. Operational Readiness & Fail-Fast Configuration** — PASS. Each feature's
  `Environment` (and thus template-file validity) is built at module-import time, so a
  missing `prompt_templates/` directory or a Jinja syntax error fails at process
  startup/import, not on first request — consistent with the existing fail-fast
  posture.
- **VIII. Library-First, Minimal Implementation** — PASS, directly on-point: Jinja2 is
  a well-maintained templating library solving exactly this problem; no hand-rolled
  templating (e.g. `str.format`/f-string macros) is introduced. Helper functions are
  intentionally thin (build `Environment` once, render, return `str`) with no extra
  indirection layers beyond what FR-001/FR-003 require.

No violations. Complexity Tracking section is not needed.

## Project Structure

### Documentation (this feature)

```text
specs/015-jinja-prompt-templates/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
├── core/
│   └── jinja.py                              # NEW — build_prompts_env(templates_dir) -> Environment
│
├── features/
│   ├── ingestion/normalizer/
│   │   ├── prompt_templates/
│   │   │   └── normalization.jinja2           # NEW — the extraction prompt
│   │   ├── prompts.py                         # NEW — get_normalization_prompt() -> Template
│   │   └── chunking.py                        # MODIFIED — _build_prompt delegates to prompts.py, then .render(...)
│   │
│   ├── chat/
│   │   ├── prompt_templates/
│   │   │   ├── summarize.jinja2               # NEW — conversation-summarization prompt
│   │   │   ├── intent_classification.jinja2   # NEW — intent-classification prompt
│   │   │   └── grounded_analysis.jinja2       # NEW — grounded spending-analysis prompt
│   │   ├── prompts.py                         # NEW — get_summary_prompt / get_intent_classification_prompt / get_grounded_analysis_prompt, each -> Template
│   │   ├── summarize.py                       # MODIFIED — summarize_node calls prompts.get_summary_prompt().render(...)
│   │   └── agents/
│   │       ├── maestro.py                     # MODIFIED — maestro_node calls prompts.get_intent_classification_prompt().render(...)
│   │       └── analysis.py                    # MODIFIED — analysis_node calls prompts.get_grounded_analysis_prompt().render(...)
│   │
│   └── plan/
│       ├── prompt_templates/
│       │   └── budget_allocation.jinja2       # NEW — budget-allocation prompt
│       ├── prompts.py                         # NEW — get_budget_allocation_prompt() -> Template
│       └── service.py                         # MODIFIED — generate_plan calls prompts.get_budget_allocation_prompt().render(...)

tests/
├── core/
│   └── test_jinja.py                          # NEW — build_prompts_env: strict-undefined, no-autoescape, caching
├── features/
│   ├── ingestion/
│   │   └── test_normalizer.py                 # EXTENDED — golden-string test for get_normalization_prompt().render(...)
│   ├── chat/
│   │   └── test_chat_prompts.py               # NEW — golden-string tests for the three chat prompts
│   └── plan/
│       └── test_plan_service.py               # EXTENDED — golden-string test for get_budget_allocation_prompt
```

**Structure Decision**: Single project, existing feature-bounded vertical-slice layout
(Constitution V) is preserved exactly. No new top-level directories. The only
cross-feature addition is `app/core/jinja.py`, placed alongside the existing shared
`config.py`/`llm.py` core modules per the spec's own Assumptions section. Each
converting feature gets its `prompt_templates/` directory and `prompts.py` module
inside its own existing slice — no feature's templates are reachable from another
feature's code.

## Complexity Tracking

*No violations — section not applicable.*
