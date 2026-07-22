# Quickstart: Validating Templated Prompt Management

Prerequisites: dependencies synced (`uv sync`), which pulls in the new `jinja2`
dependency once added to `pyproject.toml`.

## 1. Verify the shared factory fails fast on a bad directory

```bash
uv run python -c "
from pathlib import Path
from app.core.jinja import build_prompts_env
build_prompts_env(Path('/nonexistent/prompt_templates'))
"
```

Expected: raises immediately (no silent empty Environment) — confirms the
fail-fast posture (Constitution VII) referenced in `contracts/prompt-helpers.md`.

## 2. Verify strict-undefined behavior (FR-004)

```bash
uv run python -c "
from app.features.plan.prompts import get_budget_allocation_prompt
get_budget_allocation_prompt().render(user_context=None, answers={})
"
```

Expected: succeeds (both required inputs supplied via `.render(...)`). Then, to confirm
the failure path, call `.render()` with a variable omitted:

```bash
uv run python -c "
from app.features.plan.prompts import get_budget_allocation_prompt
get_budget_allocation_prompt().render(user_context=None)
"
```

Expected: raises `jinja2.UndefinedError` for the missing `answers` variable — never a
blank/placeholder string.

## 3. Verify byte-for-byte preservation (FR-005 / SC-001 / SC-003)

```bash
uv run pytest tests/features/ingestion/test_normalizer.py -k prompt -v
uv run pytest tests/features/chat/test_chat_prompts.py -v
uv run pytest tests/features/plan/test_plan_service.py -k prompt -v
```

Expected: each golden-string test passes, asserting the new template-rendered
output is identical to the previously hardcoded prompt text for the same
representative inputs (per feature: a statement chunk + category list;
conversation turns; a user message; transaction lines; user context +
questionnaire answers).

## 4. Verify no HTML-escaping of prompt content (FR-006 edge case)

```bash
uv run python -c "
from app.features.ingestion.normalizer.prompts import get_normalization_prompt
chunk = [{'type': 'text', 'text': '<b>Statement</b> total: \$100'}]
prompt = get_normalization_prompt().render(chunk=chunk, known_categories=[])
assert '&lt;b&gt;' not in prompt, 'template escaped angle brackets — autoescape must be off'
print('OK: angle brackets passed through unescaped')
"
```

## 5. Full regression pass

```bash
uv run ruff check .
uv run black --check .
uv run mypy app
uv run pytest
```

Expected: all green, with zero modifications required to any pre-existing test's
expected prompt content (SC-003) — only additive golden-string tests are new.
