# Contract: Shared factory + per-feature prompt helpers

This service has no external HTTP/CLI surface for this feature — the "interface" it
exposes is internal: a shared factory function other feature code calls, and a set of
per-feature helper functions that pipeline/agent code calls in place of today's inline
prompt strings. Documented here as a contract because multiple call sites across
features depend on these exact signatures.

## `app/core/jinja.py`

```python
def build_prompts_env(templates_dir: Path) -> jinja2.Environment:
    """Build a Jinja2 Environment scoped to `templates_dir`.

    - Loader: FileSystemLoader(templates_dir)
    - autoescape: False (plain-text prompts, never HTML-escaped)
    - undefined: StrictUndefined (missing render variable raises UndefinedError)
    - keep_trailing_newline: True (preserves exact template-file whitespace)

    Callers MUST call this once per feature (module-import time) and reuse the
    returned Environment for all subsequent renders in that feature — never
    call it again per-request.
    """
```

**Callers**: exactly one call site per converting feature's `prompts.py`
(`ingestion/normalizer/prompts.py`, `chat/prompts.py`, `plan/prompts.py`), each passing
its own `Path(__file__).parent / "prompt_templates"`.

**Failure mode**: raises at import time (`jinja2.TemplateSyntaxError` or a filesystem
error) if `templates_dir` doesn't exist or a template fails to parse — surfaces at
service startup, per Constitution VII, never on first request.

## `app/features/ingestion/normalizer/prompts.py`

```python
def get_normalization_prompt() -> Template:
    """Return the statement-normalization extraction prompt template.

    Caller renders it: get_normalization_prompt().render(
        chunk=<list[dict]>, known_categories=<list[str] | None>
    )
    Raises jinja2.UndefinedError at render time if either variable is omitted.
    """
```

**Caller**: `app/features/ingestion/normalizer/chunking.py::_build_prompt` (replaces
the current inline string-concatenation body with a call to this helper followed by
`.render(...)`).

## `app/features/chat/prompts.py`

```python
def get_summary_prompt() -> Template:
    """Return the conversation-summarization prompt template.

    Caller renders it: get_summary_prompt().render(turns=<list[str]>)
    """

def get_intent_classification_prompt() -> Template:
    """Return the intent-classification prompt template.

    Caller renders it: get_intent_classification_prompt().render(message=<str>)
    Rendered text MUST still constrain the model to exactly:
    analysis, planning, recommendation, general.
    """

def get_grounded_analysis_prompt() -> Template:
    """Return the grounded spending-analysis prompt template.

    Caller renders it: get_grounded_analysis_prompt().render(data_context=<str>)
    Rendered text MUST still instruct: cite only supplied figures, and state
    "I don't have that data yet" for anything not covered.
    """
```

**Callers**:
- `get_summary_prompt` — `app/features/chat/summarize.py::summarize_node`
- `get_intent_classification_prompt` — `app/features/chat/agents/maestro.py::maestro_node`
- `get_grounded_analysis_prompt` — `app/features/chat/agents/analysis.py::analysis_node`

## `app/features/plan/prompts.py`

```python
def get_budget_allocation_prompt() -> Template:
    """Return the budget-allocation prompt template.

    Caller renders it: get_budget_allocation_prompt().render(
        user_context=<dict | None>, answers=<dict>
    )
    Rendered text MUST still instruct: percentages summing to exactly 100,
    ONLY a JSON object as output, and include the example JSON percentage
    breakdown shape.
    """
```

**Caller**: `app/features/plan/service.py::generate_plan`.

## Cross-cutting rules (apply to every helper above)

1. Every helper takes no arguments and returns the `jinja2.Template` object itself
   — its only job is sparing the caller from naming/locating the template file
   (see `research.md` §3 for why this is the shape, not a string-returning helper).
2. The caller supplies that prompt's required render variables via `.render(...)`,
   exactly as it assembles those same inputs today for the inline prompt string
   being replaced.
3. No helper takes a template name or path as a parameter — the mapping from helper
   name to template file is fixed and internal to each `prompts.py`.
4. No helper's rendered output (once `.render(...)` is called with the inputs above)
   differs from today's hardcoded equivalent for the same inputs (FR-005) — enforced
   by the golden-string tests listed in `plan.md`'s Project Structure.
