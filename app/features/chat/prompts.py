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
_intent_classification_system_prompt = _env.get_template("intent_classification_system.jinja2")
_intent_classification_human_prompt = _env.get_template("intent_classification_human.jinja2")
_suggestions_system_prompt = _env.get_template("suggestions_system.jinja2")
_suggestions_human_prompt = _env.get_template("suggestions_human.jinja2")


def get_summary_prompt() -> Template:
    """Return the conversation-summarization prompt template.

    Caller renders it: get_summary_prompt().render(turns=<list[str]>)
    """
    return _summary_prompt


def get_intent_classification_system_prompt() -> Template:
    """Return the intent-classification SystemMessage prompt template.

    Static — takes no render variables. Caller renders it with no arguments:
    get_intent_classification_system_prompt().render()
    Rendered text constrains the model to exactly: analysis, planning,
    investment_planning, recommendation, general.
    """
    return _intent_classification_system_prompt


def get_intent_classification_human_prompt() -> Template:
    """Return the intent-classification HumanMessage prompt template.

    Caller renders it: get_intent_classification_human_prompt().render(
        message=<str>, history=<str|None>
    )
    `history` is an optional digest of recent prior turns, used to
    disambiguate an elliptical latest message; omit/None when there's no
    prior context. Split from the system prompt (RT-013) so the untrusted
    message/history content is role-separated from the task instructions
    rather than concatenated into one string.
    """
    return _intent_classification_human_prompt


def get_suggestions_system_prompt() -> Template:
    """Return the follow-up-suggestions SystemMessage prompt template.

    Static — takes no render variables. Caller renders it with no arguments:
    get_suggestions_system_prompt().render()
    """
    return _suggestions_system_prompt


def get_suggestions_human_prompt() -> Template:
    """Return the follow-up-suggestions HumanMessage prompt template.

    Caller renders it: get_suggestions_human_prompt().render(
        content=<str>, widget_type=<str|None>
    )
    Split from the system prompt (RT-013) so the untrusted reply content is
    role-separated from the task instructions rather than concatenated into
    one string.
    """
    return _suggestions_human_prompt
