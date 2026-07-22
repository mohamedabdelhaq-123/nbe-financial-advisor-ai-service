"""Prompt-template helpers for the budget-planning feature.

The Jinja2 Environment is built once at module-import time, scoped to this
feature's own `prompt_templates/` directory, and reused for every render
(FR-007). Templates are resolved at import too, so a missing directory or a
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
        user_context=<dict | None>, answers=<dict>
    )
    Rendered text still instructs percentages summing to exactly 100, ONLY a
    JSON object as output, and includes the example JSON percentage breakdown.
    """
    return _budget_allocation_prompt
