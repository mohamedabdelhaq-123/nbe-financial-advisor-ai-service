---

description: "Task list for Templated Prompt Management (015-jinja-prompt-templates)"
---

# Tasks: Templated Prompt Management

**Input**: Design documents from `/specs/015-jinja-prompt-templates/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Included. Constitution I mandates automated tests for every feature, and the
spec's own Acceptance Scenarios / Success Criteria (SC-001, SC-003, SC-004) are only
verifiable via golden-string equality tests, so test tasks are in scope here (not just
optional scaffolding).

**Organization**: Tasks are grouped by user story (US1 = P1 statement-normalization,
US2 = P2 chat prompts, US3 = P3 budget-planning) to enable independent implementation
and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every task description

## Path Conventions

Single project, existing feature-bounded vertical-slice layout (see plan.md Project
Structure) — all paths are relative to the repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the new templating dependency before any code depends on it

- [X] T001 Add `jinja2` to the `dependencies` list in `pyproject.toml` and run
      `uv lock && uv sync` to update `uv.lock` and install it (confirmed absent today
      per research.md §1 — `import jinja2` currently fails)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared template-environment factory every feature's `prompts.py`
depends on

**⚠️ CRITICAL**: No user story task can begin until this phase is complete

- [X] T002 Implement `build_prompts_env(templates_dir: Path) -> jinja2.Environment` in
      `app/core/jinja.py` per `contracts/prompt-helpers.md`: `FileSystemLoader(templates_dir)`,
      `autoescape=False`, `undefined=StrictUndefined`, `keep_trailing_newline=True`
- [X] T003 Unit tests for `build_prompts_env` in `tests/core/test_jinja.py`: (a) a
      template rendered without a required variable raises `jinja2.UndefinedError`,
      (b) a template containing `<`/`>` characters renders them unescaped
      (autoescape off), (c) calling `build_prompts_env` against a nonexistent
      directory raises at environment-build time, not silently (depends on T002)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Externalize the statement-normalization prompt (Priority: P1) 🎯 MVP

**Goal**: Move the chunk-extraction prompt out of `chunking.py`'s inline string
concatenation into `app/features/ingestion/normalizer/prompt_templates/normalization.jinja2`,
exposed via `get_normalization_prompt()` in a new `prompts.py`.

**Independent Test**: Render the normalization template (via `get_normalization_prompt().render(...)`)
with a representative statement chunk and category list, and confirm the output is
byte-for-byte identical to today's `_build_prompt` output for the same inputs — including
the case where `known_categories` is empty/`None` (category-hint clause omitted).

### Tests for User Story 1

- [X] T004 [P] [US1] Golden-string tests in `tests/features/ingestion/test_normalizer.py`
      asserting `get_normalization_prompt().render(chunk=..., known_categories=...)`
      matches the current hardcoded `_build_prompt` output verbatim, for both: a chunk
      with a non-empty `known_categories` list, and a chunk with `known_categories=None`
      (category-hint clause must be fully absent, not just empty)

### Implementation for User Story 1

- [X] T005 [US1] Create `app/features/ingestion/normalizer/prompt_templates/normalization.jinja2`,
      porting the exact current wording from `_build_prompt` in
      `app/features/ingestion/normalizer/chunking.py:75-99` — use `{{ chunk }}` for the
      JSON-serialized content and a `{% if known_categories %}...{% endif %}` block for
      the category-hint clause, preserving the exact surrounding text and whitespace
      (depends on T002)
- [X] T006 [US1] Create `app/features/ingestion/normalizer/prompts.py` exposing
      `get_normalization_prompt() -> Template`, built from `build_prompts_env(Path(__file__).parent / "prompt_templates")`
      called once at module import time (depends on T002, T005)
- [X] T007 [US1] Update `_build_prompt` in `app/features/ingestion/normalizer/chunking.py`
      to call `prompts.get_normalization_prompt().render(chunk=json.dumps(chunk), known_categories=known_categories)`
      in place of the inline string-concatenation body, removing the now-dead inline
      wording (depends on T006)

**Checkpoint**: At this point, User Story 1 is fully functional and independently
testable — the normalization pipeline sources its prompt entirely from
`normalization.jinja2`.

---

## Phase 4: User Story 2 - Externalize chat-agent prompts (Priority: P2)

**Goal**: Move the conversation-summarization, intent-classification, and
grounded-analysis prompts out of their respective inline string constructions in
`summarize.py`, `agents/maestro.py`, and `agents/analysis.py` into three template files
under `app/features/chat/prompt_templates/`, exposed via a new `chat/prompts.py`.

**Independent Test**: Render each of the three chat templates with representative
inputs (earlier conversation turns; a user message; transaction lines) and confirm each
matches its current hardcoded equivalent — independently of US1/US3.

### Tests for User Story 2

- [X] T008 [P] [US2] Golden-string tests in `tests/features/chat/test_chat_prompts.py`
      for all three chat prompts: `get_summary_prompt().render(turns=...)` matches the
      current `summarize_node` prompt text; `get_intent_classification_prompt().render(message=...)`
      matches the current `maestro_node` prompt text and still names exactly
      `analysis, planning, recommendation, general`; `get_grounded_analysis_prompt().render(data_context=...)`
      matches the current `analysis_node` prompt text and still instructs citing only
      supplied figures

### Implementation for User Story 2

- [X] T009 [P] [US2] Create `app/features/chat/prompt_templates/summarize.jinja2`,
      porting the exact wording from `summarize_node` in `app/features/chat/summarize.py:27-29`
      (`"Summarise the following conversation turns concisely:\n\n" + joined turns`),
      with `{{ turns }}` (or a `{% for %}` loop over pre-formatted turn lines) supplying
      the joined content (depends on T002)
- [X] T010 [P] [US2] Create `app/features/chat/prompt_templates/intent_classification.jinja2`,
      porting the exact wording from `maestro_node` in `app/features/chat/agents/maestro.py:69-73`,
      with `{{ message }}` for the user message and the fixed intent-label sentence
      preserved verbatim (depends on T002)
- [X] T011 [P] [US2] Create `app/features/chat/prompt_templates/grounded_analysis.jinja2`,
      porting the exact wording from `analysis_node` in `app/features/chat/agents/analysis.py:57-61`,
      with `{{ data_context }}` for the joined transaction lines (depends on T002)
- [X] T012 [US2] Create `app/features/chat/prompts.py` exposing `get_summary_prompt()`,
      `get_intent_classification_prompt()`, and `get_grounded_analysis_prompt()` (each
      `-> Template`), built from a single `build_prompts_env(Path(__file__).parent / "prompt_templates")`
      module-level singleton (depends on T002, T009, T010, T011)
- [X] T013 [P] [US2] Update `summarize_node` in `app/features/chat/summarize.py` to call
      `prompts.get_summary_prompt().render(turns=...)` in place of its inline prompt
      string, passing the same pre-formatted turn lines it builds today (depends on T012)
- [X] T014 [P] [US2] Update `maestro_node` in `app/features/chat/agents/maestro.py` to
      call `prompts.get_intent_classification_prompt().render(message=text)` in place
      of its inline prompt string (depends on T012)
- [X] T015 [P] [US2] Update `analysis_node` in `app/features/chat/agents/analysis.py` to
      call `prompts.get_grounded_analysis_prompt().render(data_context=data_context)` in
      place of its inline prompt string (depends on T012)

**Checkpoint**: At this point, User Stories 1 AND 2 both work independently — all
chat-agent prompts are sourced from their templates.

---

## Phase 5: User Story 3 - Externalize the budget-planning prompt (Priority: P3)

**Goal**: Move the budget-allocation prompt out of `generate_plan`'s inline string
construction in `app/features/plan/service.py` into
`app/features/plan/prompt_templates/budget_allocation.jinja2`, exposed via a new
`plan/prompts.py`.

**Independent Test**: Render the planning template with sample user context and
questionnaire answers and confirm the result matches the current hardcoded prompt,
independently of US1/US2.

### Tests for User Story 3

- [X] T016 [P] [US3] Golden-string test in `tests/features/plan/test_plan_service.py`
      asserting `get_budget_allocation_prompt().render(user_context=..., answers=...)`
      matches the current `generate_plan` prompt text verbatim, including the example
      JSON percentage-breakdown literal

### Implementation for User Story 3

- [X] T017 [US3] Create `app/features/plan/prompt_templates/budget_allocation.jinja2`,
      porting the exact wording from `generate_plan` in `app/features/plan/service.py:54-60`,
      with `{{ user_context }}` and `{{ answers }}` for the interpolated dicts and the
      example JSON breakdown preserved verbatim and unescaped (depends on T002)
- [X] T018 [US3] Create `app/features/plan/prompts.py` exposing
      `get_budget_allocation_prompt() -> Template`, built from
      `build_prompts_env(Path(__file__).parent / "prompt_templates")` (depends on T002, T017)
- [X] T019 [US3] Update `generate_plan` in `app/features/plan/service.py` to call
      `prompts.get_budget_allocation_prompt().render(user_context=user_context, answers=answers)`
      in place of its inline prompt string (depends on T018)

**Checkpoint**: All three user stories are now independently functional — every prompt
identified in the spec is sourced from a template file (SC-001).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Full-suite verification once all three stories are converted

- [X] T020 [P] Run `uv run ruff check .`, `uv run black --check .`, and `uv run mypy app`
      across all new/modified files (`app/core/jinja.py`, the three `prompts.py`
      modules, and the five modified call sites) and fix any findings
- [X] T021 [P] Run the full existing test suite (`uv run pytest`) and confirm every
      pre-existing test passes unmodified (SC-003) — none of `test_normalizer.py`,
      `test_maestro.py`, `test_streaming.py`, `test_planner_integration.py` should
      require expected-content changes
- [X] T022 Execute the `quickstart.md` validation steps end-to-end (fail-fast on a bad
      directory, strict-undefined failure, byte-for-byte golden tests, no-HTML-escaping
      check) and confirm all pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup (needs `jinja2` installed) — BLOCKS all
  user stories
- **User Stories (Phase 3-5)**: All depend on Foundational (T002) completion; the three
  stories touch entirely disjoint files (`ingestion/normalizer/*` vs `chat/*` vs
  `plan/*`) and can proceed in parallel or in priority order (P1 → P2 → P3)
- **Polish (Phase 6)**: Depends on all three user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational — no dependency on US2/US3
- **User Story 2 (P2)**: Can start after Foundational — no dependency on US1/US3
- **User Story 3 (P3)**: Can start after Foundational — no dependency on US1/US2

(All three stories are independent by construction — Constitution V's vertical-slice
boundary means no feature's `prompts.py` or templates are reachable from another
feature.)

### Within Each User Story

- Golden-string test task is written against the not-yet-existing helper (fails until
  the template + `prompts.py` exist), then: template file → `prompts.py` → call-site
  update → test passes
- Template file before `prompts.py` (helper loads the template)
- `prompts.py` before the call-site update (call site imports the helper)
- Story complete (call site updated, test passing) before moving to the next priority

### Parallel Opportunities

- T001 (Setup) has no parallel siblings in this feature
- T002 and T003 in Foundational are sequential (T003 tests T002's output)
- Once Foundational (T002) is done, all three user story phases (3, 4, 5) can proceed
  in parallel — different developers, zero file overlap
- Within US2, the three template-file tasks (T009, T010, T011) are parallel; the three
  call-site updates (T013, T014, T015) are parallel (three different files)
- T020 and T021 in Polish are parallel (independent tool invocations)

---

## Parallel Example: User Story 2

```bash
# Launch the three chat template files together (different files, no interdependency):
Task: "Create app/features/chat/prompt_templates/summarize.jinja2"
Task: "Create app/features/chat/prompt_templates/intent_classification.jinja2"
Task: "Create app/features/chat/prompt_templates/grounded_analysis.jinja2"

# After chat/prompts.py (T012) exists, launch the three call-site updates together:
Task: "Update summarize_node in app/features/chat/summarize.py"
Task: "Update maestro_node in app/features/chat/agents/maestro.py"
Task: "Update analysis_node in app/features/chat/agents/analysis.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002-T003) — CRITICAL, blocks all stories
3. Complete Phase 3: User Story 1 (T004-T007)
4. **STOP and VALIDATE**: run `tests/features/ingestion/test_normalizer.py`, confirm
   golden-string equality and no regression in existing normalizer tests
5. Deploy/demo if ready — normalization is the highest-stakes prompt, so proving the
   templating approach here first de-risks US2/US3

### Incremental Delivery

1. Setup + Foundational → template infrastructure ready
2. Add User Story 1 → test independently → demo (MVP)
3. Add User Story 2 → test independently → demo
4. Add User Story 3 → test independently → demo (closes SC-001: 100% of hardcoded
   prompts converted)

### Parallel Team Strategy

With multiple developers, once Foundational (T002-T003) is done:
- Developer A: User Story 1 (`ingestion/normalizer/*`)
- Developer B: User Story 2 (`chat/*`)
- Developer C: User Story 3 (`plan/*`)

No merge conflicts expected — the three stories touch entirely disjoint file sets.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Verify each golden-string test fails before its template/`prompts.py`/call-site
  update exists, then passes after
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently
- FR-005 (byte-for-byte preservation) is the correctness bar for every template task —
  when in doubt, copy the current Python string literal into the template file first
  and only then substitute `{{ }}`/`{% %}` at the exact interpolation points
