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
_grounded_analysis_prompt = _env.get_template("grounded_analysis.jinja2")


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


def get_grounded_analysis_prompt() -> Template:
    """Return the grounded spending-analysis prompt template.

    Caller renders it: get_grounded_analysis_prompt().render(data_context=<str>)
    Rendered text still instructs citing only supplied figures and stating
    "I don't have that data yet" for anything not covered.
    """
    return _grounded_analysis_prompt
