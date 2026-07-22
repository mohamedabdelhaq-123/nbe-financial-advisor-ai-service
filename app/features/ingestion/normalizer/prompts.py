"""Prompt-template helpers for the statement-normalization feature.

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
_normalization_prompt = _env.get_template("normalization.jinja2")


def get_normalization_prompt() -> Template:
    """Return the statement-normalization extraction prompt template.

    Caller renders it: get_normalization_prompt().render(
        chunk=<JSON-serialized str>, known_categories=<list[str] | None>
    )
    Raises jinja2.UndefinedError at render time if either variable is omitted.
    """
    return _normalization_prompt
