# Phase 1 Data Model: Templated Prompt Management

This feature introduces no persisted data (no DB tables, no Pydantic schemas crossing
a service boundary). Its "entities" are structural/code artifacts, listed here per the
spec's Key Entities section, mapped to concrete shapes.

## Entity: Prompt Template

A single `.jinja2` file holding one prompt's wording, scoped to the feature that uses
it, parameterized by the variables it accepts.

| Feature | Template file | Path (relative to `app/features/`) | Required variables |
|---|---|---|---|
| Ingestion normalizer | `normalization.jinja2` | `ingestion/normalizer/prompt_templates/normalization.jinja2` | `chunk` (JSON-serialized string), `known_categories` (`list[str]`, may be empty — controls the conditional category-hint block) |
| Chat | `summarize.jinja2` | `chat/prompt_templates/summarize.jinja2` | `turns` (list of `"{type}: {content}"` lines already formatted by the caller) |
| Chat | `intent_classification.jinja2` | `chat/prompt_templates/intent_classification.jinja2` | `message` (`str`, the user's raw message text) |
| Chat | `grounded_analysis.jinja2` | `chat/prompt_templates/grounded_analysis.jinja2` | `data_context` (`str`, newline-joined transaction lines) |
| Plan | `budget_allocation.jinja2` | `plan/prompt_templates/budget_allocation.jinja2` | `user_context` (`dict \| None`), `answers` (`dict`) |

Validation rule (all templates, FR-004): rendering with any required variable absent
from the render call MUST raise `jinja2.UndefinedError` (enforced by the shared
`Environment`'s `StrictUndefined`, not per-template logic).

Invariant (all templates, FR-006): no variable is HTML-escaped — the `Environment`
that loads every template in this table has `autoescape=False`.

## Entity: Feature Template Directory

A per-feature directory named `prompt_templates/`, sibling to that feature's
`prompts.py`, containing only that feature's own templates. Three exist after this
feature: `app/features/ingestion/normalizer/prompt_templates/`,
`app/features/chat/prompt_templates/`, `app/features/plan/prompt_templates/`. No
directory is referenced by any `prompts.py` other than its own feature's (enforced by
construction — each `prompts.py` builds its `Environment` from
`Path(__file__).parent / "prompt_templates"`, never an absolute or cross-feature path).

## Entity: Prompt Helper

A zero-argument, per-feature function in that feature's `prompts.py` that locates and
returns the `jinja2.Template` object for one prompt — callers then call `.render(...)`
on the returned template, supplying that prompt's specific inputs themselves. One
helper per template in the table above:

| Helper | Signature | Feature |
|---|---|---|
| `get_normalization_prompt` | `() -> Template` — caller: `.render(chunk=..., known_categories=...)` | ingestion/normalizer |
| `get_summary_prompt` | `() -> Template` — caller: `.render(turns=...)` | chat |
| `get_intent_classification_prompt` | `() -> Template` — caller: `.render(message=...)` | chat |
| `get_grounded_analysis_prompt` | `() -> Template` — caller: `.render(data_context=...)` | chat |
| `get_budget_allocation_prompt` | `() -> Template` — caller: `.render(user_context=..., answers=...)` | plan |

Each helper's job is only to spare the caller from naming/locating the template file
(FR-003); the required-variable set from the Prompt Template table above is supplied
by the caller at `.render()` time, exactly as today's call sites already assemble
those same inputs for their inline prompt strings. No helper accepts a template
name/path as a parameter — the mapping from helper name to template file is fixed
inside each `prompts.py`.

## Relationships

```
core/jinja.py (build_prompts_env)
        │  called once, at import time, by each feature's prompts.py
        ▼
feature/prompts.py  ──uses──▶  feature/prompt_templates/*.jinja2
        │
        │  returns rendered str
        ▼
feature call site (chunking.py / summarize.py / maestro.py / analysis.py / service.py)
        │
        ▼
   LLM invocation (unchanged: get_chat_model().ainvoke(prompt_str))
```

No entity here is persisted, versioned, or exposed over any API — this is purely an
internal code-organization change within each feature's existing vertical slice
(Constitution V).
