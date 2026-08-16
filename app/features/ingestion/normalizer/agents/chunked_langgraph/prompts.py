"""Prompt-template helpers for the statement-normalization strategy.

The Jinja2 Environment is built once at module-import time, scoped to this
strategy's own `prompt_templates/` directory, and reused for every render.
Templates are resolved at import too, so a missing directory or a syntactically
broken template fails at process startup, not on first request (Constitution VII).

`prompt_version` (FR-013) is a short content hash of the committed template
source, computed once at load time — additive to the git-tracked file, not a
migration to a hosted prompt-management store.
"""

import hashlib
from pathlib import Path

from jinja2 import Template

from app.core.jinja import build_prompts_env

_TEMPLATE_DIR = Path(__file__).parent / "prompt_templates"
_env = build_prompts_env(_TEMPLATE_DIR)
_normalization_prompt = _env.get_template("normalization.jinja2")

# FR-013: stable identifier for the committed template content. Changes when
# the template file changes, identical across repeated calls and processes.
with (_TEMPLATE_DIR / "normalization.jinja2").open("rb") as _f:
    PROMPT_VERSION = hashlib.sha256(_f.read()).hexdigest()[:8]


def get_normalization_prompt() -> Template:
    """Return the statement-normalization extraction prompt template.

    Caller renders it: get_normalization_prompt().render(
        chunk=<markdown str>, known_categories=<list[str] | None>
    )
    Raises jinja2.UndefinedError at render time if either variable is omitted.
    """
    return _normalization_prompt


def get_prompt_version() -> str:
    """Return the short content-hash version of the normalization template."""
    return PROMPT_VERSION
