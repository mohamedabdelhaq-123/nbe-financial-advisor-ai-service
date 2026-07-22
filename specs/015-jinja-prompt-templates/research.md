# Phase 0 Research: Templated Prompt Management

## 1. Template engine & dependency

**Decision**: Add `jinja2` as a new direct dependency in `pyproject.toml` (confirmed
absent today — `import jinja2` fails in the current environment).

**Rationale**: Jinja2 is the explicitly mandated engine per the spec's Assumptions
section, and Constitution VIII (Library-First, Minimal Implementation) directs
preferring a well-maintained library primitive over hand-rolled templating (e.g.
f-string/`str.format` assembly, which is exactly what today's code does and what this
feature replaces).

**Alternatives considered**: `string.Template` (stdlib) — rejected, lacks conditionals
(`{% if %}`) needed to reproduce the normalization prompt's optional category-hint
clause (FR-002/edge case in spec) without falling back to Python-side string branching,
which would defeat the point of externalizing wording. Mako / other template
engines — rejected, not requested and would add a second templating dependency for no
benefit over Jinja2.

## 2. Environment construction & loader

**Decision**: `build_prompts_env(templates_dir: Path) -> jinja2.Environment` in
`app/core/jinja.py`, implemented as:

```python
Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)
```

Each feature's `prompts.py` calls this once at module import time with its own
`Path(__file__).parent / "prompt_templates"`, and stores the result in a module-level
variable.

**Rationale**:
- `FileSystemLoader` rooted at a plain `pathlib.Path` works identically in the `dev`
  and `prod` Docker targets (both do `COPY . .` — templates ship as regular files
  alongside the `.py` source, no package-data/wheel step involved) and under local
  `uv run`/pytest, with zero extra configuration.
- `autoescape=False` is required by FR-006 (plain text to a model, not HTML) — Jinja2's
  usual autoescape defaults target HTML/XML output and would corrupt OCR'd statement
  content containing angle brackets (the spec's own edge case).
- `undefined=StrictUndefined` is required by FR-004 — any `{{ missing_var }}` raises
  `jinja2.UndefinedError` at render time instead of silently substituting an empty
  string, which the default `Undefined` class would do.
- `keep_trailing_newline=True` avoids Jinja2's default behavior of swallowing the
  template file's final newline, which matters for FR-005's byte-for-byte
  preservation guarantee where the original hardcoded string's exact trailing
  whitespace must be reproduced.
- A **module-level singleton per feature** (rather than a shared cache keyed by path
  inside `core/jinja.py`) satisfies FR-007 ("reuse the same loaded template engine")
  with no extra state: Python's own import-caching means `prompts.py` — and therefore
  its `Environment` — is constructed exactly once per process, identically to how
  `mineru_client.py`/`normalizer/__init__.py` already memoize their singletons at
  module scope. Adding an LRU-cache layer inside `core/jinja.py` was considered and
  rejected as unnecessary indirection (Constitution VIII) given the per-feature
  singleton already achieves the requirement.

**Alternatives considered**: `jinja2.PackageLoader` — rejected, it assumes an
installed/importable package structure with `importlib.resources` semantics, which adds
complexity (and a resource-loading edge case around zipped packages) with no upside
here since the service is never installed as a wheel — it runs from a plain copied
source tree in both dev and prod images.

## 3. Helper-function shape: template handle vs. rendered string

**Decision**: Each feature's `prompts.py` exposes zero-argument functions that locate
and return the `jinja2.Template` object itself — e.g. `get_normalization_prompt() ->
Template`, `get_intent_classification_prompt() -> Template` — via
`_env.get_template("<name>.jinja2")`. The caller then supplies that specific render's
inputs itself: `get_normalization_prompt().render(chunk=chunk, known_categories=known_categories)`.

**Rationale**: This is the shape the feature request itself specifies explicitly
(`get_normalization_prompt().render()`), confirmed as the intended design: the helper's
job is only to save the caller from locating/naming the template file (FR-003 — "ask
for the normalization prompt... rather than assembling or locating template files
itself"); supplying the render inputs stays the caller's job, same as it is today when
the caller assembles the inline string. `StrictUndefined` (research.md §2) still
enforces FR-004 at `.render()` time regardless of which side of the call holds the
input values, so this shape loses no correctness guarantee versus a string-returning
helper.

**Alternatives considered**: Helper takes the prompt's inputs as typed parameters and
returns the fully rendered `str` directly (no caller-side `.render()`) — considered
because the spec's Key Entities prose says a helper is used "to obtain a fully rendered
prompt string," and because a typed signature gives `mypy` a compile-time check on
required inputs that a bare `.render(**kwargs)` doesn't. Rejected on explicit
correction: the feature request's own example is definitive here, and the helper's
sole responsibility is template lookup, not input plumbing — callers keep assembling
and passing render inputs exactly as they do today, just against a loaded `Template`
instead of a hardcoded string.

## 4. Preserving exact current wording (FR-005 / byte-for-byte)

**Decision**: For each of the five prompts, the template file's content is copied
verbatim from the current f-string/concatenation output (with `{{ variable }}`
substituted for the current Python interpolation points, and `{% if %}`/`{% endif %}`
for the one conditional segment — the normalization prompt's category-hint clause).
Each converted call site gets (or already has, per existing test-suite conventions) a
unit test that renders the template with representative inputs and asserts the result
equals a captured golden string equal to today's hardcoded output for the same inputs,
directly exercising spec Acceptance Scenarios (US1 #1–2, US2 #1–3, US3 #1) and SC-001/SC-003.

**Rationale**: This is the only way to mechanically prove "no wording change" per FR-005
and the spec's own Assumptions ("mechanical refactor... not a rewrite of what the
prompts say"). Existing tests were confirmed (by inspection) not to assert on literal
prompt string content today — they stub the LLM's `ainvoke` and assert on behavior/output
shape — so no existing test needs modification; new golden-string tests are additive only.

**Alternatives considered**: Manual eyeballing / no automated wording-equality check —
rejected, doesn't satisfy SC-004's "100% of the time" bar for a mechanical, reviewable
guarantee, and risks silent prompt drift during the refactor.

## 5. Where each of the five prompts currently lives (source-of-truth for conversion)

| Prompt | Current location | Notes |
|---|---|---|
| Statement-normalization extraction | `app/features/ingestion/normalizer/chunking.py::_build_prompt` | Has one conditional segment (category hint) |
| Chat conversation-summarization | `app/features/chat/summarize.py::summarize_node` (inline prompt string) | Only built on the non-mock path |
| Chat intent-classification | `app/features/chat/agents/maestro.py::maestro_node` (inline prompt string) | Only built on the non-mock path; fixed intent label set must remain in the template text |
| Chat grounded-analysis | `app/features/chat/agents/analysis.py::analysis_node` (inline prompt string) | Only built on the non-mock path |
| Budget-allocation | `app/features/plan/service.py::generate_plan` (inline prompt string) | Only built on the non-mock path; includes an example JSON literal that must render unescaped |

**Rationale**: All five prompts are only constructed on the `settings.chat_model.use_mock
== False` path — the mock paths return canned strings and are out of scope (they don't
hardcode a *prompt*, just a canned reply). Confirmed by reading each file directly.

## 6. Constitution alignment check

No principle blocks this feature; see the Constitution Check section of `plan.md` for
the full per-principle walkthrough. No `NEEDS CLARIFICATION` markers remain — the spec
and this research fully resolve technical unknowns.
