"""Shared Jinja2 environment factory for prompt templates.

Each feature that renders prompts calls `build_prompts_env` once at module-import
time, scoped to that feature's own `prompt_templates/` directory, and reuses the
returned `Environment` for every subsequent render (FR-007).

The environment is configured for plain-text prompts (autoescape off — FR-006)
that fail fast on any missing render variable (StrictUndefined — FR-004) and
preserve exact template-file whitespace (keep_trailing_newline — FR-005).
"""

from pathlib import Path

import jinja2


def build_prompts_env(templates_dir: Path) -> jinja2.Environment:
    """Build a Jinja2 Environment scoped to `templates_dir`.

    - Loader: FileSystemLoader(templates_dir)
    - autoescape: False (plain-text prompts, never HTML-escaped)
    - undefined: StrictUndefined (missing render variable raises UndefinedError)
    - keep_trailing_newline: True (preserves exact template-file whitespace)

    Callers MUST call this once per feature (module-import time) and reuse the
    returned Environment for all subsequent renders in that feature — never
    call it again per-request.

    Raises at environment-build time (a filesystem error if `templates_dir`
    doesn't exist, or a TemplateSyntaxError later if a template fails to
    parse) so the failure surfaces at process startup per Constitution VII,
    never on the first request.
    """
    if not templates_dir.is_dir():
        raise FileNotFoundError(f"prompt_templates directory not found: {templates_dir}")
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_dir),
        autoescape=False,
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
