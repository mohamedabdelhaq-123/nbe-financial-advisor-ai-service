"""Prompt-template helpers for the budget-planning feature.

The Jinja2 Environment is built once at module-import time, scoped to this
feature's own `prompt_templates/` directory, and reused for every render.
Templates are resolved at import too, so a missing directory or a
syntactically broken template fails at process startup, not on first request
(Constitution VII).
"""

from pathlib import Path

from jinja2 import Template

from app.core.jinja import build_prompts_env

_env = build_prompts_env(Path(__file__).parent / "prompt_templates")
_budget_allocation_prompt = _env.get_template("budget_allocation.jinja2")


def get_budget_allocation_prompt() -> Template:
    """Return the budget-allocation prompt template.

    Caller renders it: get_budget_allocation_prompt().render(
        avg_monthly_income=<Any>, avg_monthly_recurring_expense=<Any>,
        savings_goal_name=<Any>, savings_goal_target_amount=<Any>,
        savings_goal_timeline_months=<Any>, savings_goal_answer=<Any>,
        answers=<dict>, known_categories=<list[str]>, example_categories=<str>,
    )
    `example_categories` is precomputed by the caller (Python `!r}` repr
    formatting has no direct Jinja equivalent) as
    `', '.join(f'{c!r}: 10' for c in known_categories)`.
    """
    return _budget_allocation_prompt
