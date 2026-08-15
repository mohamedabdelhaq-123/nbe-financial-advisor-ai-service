# Feature Specification: Templated Prompt Management

**Feature Branch**: `015-jinja-prompt-templates`

**Created**: 2026-07-22

**Status**: Draft

**Input**: User description: "currently we hard code the prompts for chats, normalization etc. We need to use a template engine and store prompt templates under a prompt_templates subdirectory for each feature that hardcodes a prompt. We shall use jinja we shall make a shared build_prompts_env in core/jinja.py ... which would be called from a prompts.py under each feature that needs prompts ... additionally, prompts.py can create helpers like get_system_prompt, or get_normalization_prompt().render(), etc."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Externalize the statement-normalization prompt (Priority: P1)

As a developer maintaining the statement-normalization pipeline, I want the extraction prompt's wording stored in a template file rather than assembled inline in Python, so I can review and tune the exact instructions sent to the model (date formats, category handling, `extra_fields` rules) without touching pipeline code.

**Why this priority**: Normalization is the highest-stakes prompt in the service — it drives structured extraction of real financial transactions from bank statements, and prompt wording changes here have historically required careful, isolated review (see the chunk-sizing tuning already documented in the codebase). It's also the most complex hardcoded prompt today, so it validates the templating approach under the hardest case first.

**Independent Test**: Can be fully tested by rendering the normalization template with a representative statement chunk and category list, and confirming the rendered text is byte-for-byte identical to today's hardcoded prompt output for the same inputs — deliverable and verifiable without any other feature being converted.

**Acceptance Scenarios**:

1. **Given** a statement chunk and a list of known categories, **When** the normalization prompt is rendered, **Then** the resulting text matches the current hardcoded prompt's content and structure exactly.
2. **Given** no known categories are supplied, **When** the normalization prompt is rendered, **Then** the category-constraint instruction is omitted, matching current behavior.
3. **Given** a developer edits only the template file's wording, **When** the pipeline next runs, **Then** the new wording is sent to the model with no Python code change required.

---

### User Story 2 - Externalize chat-agent prompts (Priority: P2)

As a developer maintaining the chat assistant, I want the conversation-summarization prompt, the intent-classification prompt, and the grounded-analysis prompt each stored as template files under the chat feature, so prompt wording for the assistant's behavior is reviewable and editable independently of the orchestration and data-fetching logic around it.

**Why this priority**: These three prompts directly shape user-facing assistant behavior (what gets summarized, how intent is classified, how spending answers are grounded) but are currently scattered as inline string concatenation across multiple files, making them hard to audit together.

**Independent Test**: Can be fully tested by rendering each of the three chat templates with representative inputs (conversation turns, a user message, transaction lines) and confirming each rendered result matches its current hardcoded equivalent, independent of the normalization or planning prompts.

**Acceptance Scenarios**:

1. **Given** a set of earlier conversation turns, **When** the summarization prompt is rendered, **Then** the resulting text matches the current hardcoded summarization prompt for the same turns.
2. **Given** a user message, **When** the intent-classification prompt is rendered, **Then** the resulting text matches the current hardcoded classification prompt and still constrains the model to the same fixed set of intent labels.
3. **Given** a list of transaction lines for a user, **When** the grounded-analysis prompt is rendered, **Then** the resulting text matches the current hardcoded analysis prompt, including the instruction to only cite supplied figures.

---

### User Story 3 - Externalize the budget-planning prompt (Priority: P3)

As a developer maintaining the budgeting feature, I want the budget-allocation prompt stored as a template file under the plan feature, so the instructions and example JSON shape given to the model are easy to find and adjust.

**Why this priority**: Lower risk and lower change frequency than normalization or chat, but converting it completes the sweep of every currently-hardcoded prompt in the service, closing the gap rather than leaving one inconsistent feature behind.

**Independent Test**: Can be fully tested by rendering the planning template with sample user context and questionnaire answers and confirming the result matches the current hardcoded prompt, independent of the other two stories.

**Acceptance Scenarios**:

1. **Given** user context and questionnaire answers, **When** the budget-allocation prompt is rendered, **Then** the resulting text matches the current hardcoded prompt, including the example JSON percentage breakdown.

---

### Edge Cases

- What happens when a template references a variable that the caller forgot to pass in? Rendering MUST fail immediately with a clear error rather than silently producing a prompt with blank or default text — a silently incomplete financial-extraction or classification prompt is worse than a startup/runtime failure.
- What happens when a feature's `prompt_templates` directory is missing or a named template file doesn't exist? Rendering MUST fail immediately with a clear error identifying the missing template, rather than falling back to hardcoded text.
- What happens when a template's rendered content contains characters that look like markup (e.g. angle brackets in OCR'd statement content)? Rendering MUST NOT escape or alter that content — prompts are plain text sent to a model, not HTML.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide one shared template-environment factory, usable by every feature, that any feature can call to obtain a template engine scoped to that feature's own template directory.
- **FR-002**: Every feature identified as currently hardcoding a prompt (statement normalization, chat summarization, chat intent classification, chat grounded analysis, budget planning) MUST have its prompt text moved into one or more template files stored in a dedicated template directory scoped to that feature.
- **FR-003**: Each such feature MUST expose its prompt-rendering behavior through a small set of named helper functions scoped to that feature, so calling code asks for "the normalization prompt" or "the intent-classification prompt" rather than assembling or locating template files itself.
- **FR-004**: Rendering any prompt template with a missing required input MUST raise an error rather than silently substituting blank or default content.
- **FR-005**: Converting a prompt to a template MUST preserve its exact current wording and structure — this is a mechanical externalization, not a rewording, so existing behavior and any tests asserting on prompt content continue to pass unchanged.
- **FR-006**: The template engine MUST treat prompt content as plain text — output MUST NOT be HTML-escaped, since prompts are sent to a language model, not rendered in a browser.
- **FR-007**: Repeated requests to render the same feature's prompts MUST reuse the same loaded template engine rather than re-reading template files from disk on every call.
- **FR-008**: Editing a template file's wording MUST NOT require any change to the Python code that calls it, for inputs the template already accepts.

### Key Entities

- **Prompt Template**: A single named template file holding the wording for one prompt (e.g. the normalization extraction prompt, the intent-classification prompt), scoped to the feature that uses it, parameterized by the inputs that prompt needs (e.g. statement chunk content, known categories, conversation turns, user message).
- **Feature Template Directory**: A per-feature collection of that feature's prompt templates, isolated from every other feature's templates.
- **Prompt Helper**: A per-feature named entry point (e.g. "get the normalization prompt", "get the intent-classification prompt") that callers use to obtain a fully rendered prompt string for given inputs, without needing to know template file names or locations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the prompts identified as currently hardcoded (statement normalization, chat summarization, chat intent classification, chat grounded analysis, budget planning) are sourced from template files rather than inline Python string construction.
- **SC-002**: A developer can change a covered prompt's wording by editing exactly one template file, with zero Python code changes, for any input the prompt already accepts.
- **SC-003**: Every existing automated test that exercises a converted prompt continues to pass without modification to its expected prompt content, confirming the externalization introduced no behavior change.
- **SC-004**: Rendering a covered prompt with a missing required input fails with an immediate, clear error 100% of the time — never a silently incomplete prompt sent to the model.

## Assumptions

- The five prompts identified by scanning the current codebase — statement-normalization extraction, chat conversation-summarization, chat intent-classification, chat grounded-analysis, and budget-allocation — are the complete set of "hardcoded prompts" in scope. Any other free-text sent to the model that isn't a distinct, identifiable prompt (e.g. the plain disclaimer suffix appended to assistant replies) is out of scope, since it isn't itself an LLM-facing instruction prompt.
- Jinja2 is the mandated template engine and each converting feature gets its own `prompt_templates` subdirectory plus a small helper module, per the requester's explicit direction, mirroring the existing per-feature module layout already used elsewhere in the codebase (e.g. swappable-client patterns in normalization and MinerU).
- Strict undefined-variable behavior (fail on missing input) is required for every template, since these prompts feed financial-data extraction and user-facing assistant responses where a silently incomplete prompt is a correctness and compliance risk, not just a cosmetic one.
- This is a mechanical refactor of *how* existing prompt text is stored and assembled, not a rewrite of *what* the prompts say — no prompt wording changes are in scope.
- The shared template-environment factory is a cross-feature utility (alongside existing shared modules like configuration and LLM access) rather than owned by any single feature.
