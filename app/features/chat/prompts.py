"""Prompt-template helpers for the chat feature.

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
_summary_prompt = _env.get_template("summarize.jinja2")
_intent_classification_prompt = _env.get_template("intent_classification.jinja2")


def get_summary_prompt() -> Template:
    """Return the conversation-summarization prompt template.

    Caller renders it: get_summary_prompt().render(turns=<list[str]>)
    """
    return _summary_prompt


def get_intent_classification_prompt() -> Template:
    """Return the intent-classification prompt template.

    Caller renders it: get_intent_classification_prompt().render(message=<str>)
    Rendered text still constrains the model to exactly:
    analysis, planning, recommendation, general.
    """
    return _intent_classification_prompt
