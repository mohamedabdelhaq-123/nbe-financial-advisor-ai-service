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
_maestro_routing_system_prompt = _env.get_template("maestro_routing_system.jinja2")
_maestro_routing_human_prompt = _env.get_template("maestro_routing_human.jinja2")
_suggestions_system_prompt = _env.get_template("suggestions_system.jinja2")
_suggestions_human_prompt = _env.get_template("suggestions_human.jinja2")
_investment_extraction_system_prompt = _env.get_template("investment_extraction_system.jinja2")
_investment_extraction_human_prompt = _env.get_template("investment_extraction_human.jinja2")


def get_summary_prompt() -> Template:
    """Return the conversation-summarization prompt template.

    Caller renders it: get_summary_prompt().render(turns=<list[str]>)
    """
    return _summary_prompt


def get_maestro_routing_system_prompt() -> Template:
    """Return the structured Maestro-routing SystemMessage template.

    Caller supplies the route catalogue rendered from ``routing.ROUTE_SPECS``
    so capability descriptions have one source of truth.
    """
    return _maestro_routing_system_prompt


def get_maestro_routing_human_prompt() -> Template:
    """Return the untrusted conversation portion of the routing prompt.

    Caller renders it: get_maestro_routing_human_prompt().render(
        message=<str>, history=<str|None>, last_active_route=<str|None>
    )
    `history` is an optional digest of recent prior turns, used to
    disambiguate an elliptical latest message; omit/None when there's no
    prior context. `last_active_route` names the capability that produced
    the last `route` outcome (None if none yet, or stale/unrecognized), so
    the classifier can tell a reflective follow-up about a prior reply from
    a fresh request for a different capability — see state.py's
    `last_active_route` field and maestro.py's `_decision_state`. Split from
    the system prompt (RT-013) so the untrusted message/history content is
    role-separated from the task instructions rather than concatenated into
    one string.
    """
    return _maestro_routing_human_prompt


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


def get_investment_extraction_system_prompt() -> Template:
    """Return the investment-answer-extraction SystemMessage template.

    Static — takes no render variables. Caller renders it with no arguments:
    get_investment_extraction_system_prompt().render()
    """
    return _investment_extraction_system_prompt


def get_investment_extraction_human_prompt() -> Template:
    """Return the untrusted conversation portion of the investment-answer-
    extraction prompt.

    Caller renders it: get_investment_extraction_human_prompt().render(
        message=<str>, missing_fields=<list[str]>
    )
    `missing_fields` names whichever of confirmed_amount/objective/risk/
    horizon/liquidity are not yet answered, so the model knows what this
    turn is actually trying to fill — see agents/investment.py's
    InvestmentAnswerExtraction. Split from the system prompt (RT-013) so the
    untrusted message content is role-separated from the task instructions
    rather than concatenated into one string.
    """
    return _investment_extraction_human_prompt
