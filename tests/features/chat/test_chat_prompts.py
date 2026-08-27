"""Prompt-template tests for summary and structured Maestro routing."""

from app.features.chat.prompts import (
    get_maestro_routing_human_prompt,
    get_maestro_routing_system_prompt,
    get_summary_prompt,
)
from app.features.chat.routing import ROUTE_SPECS, route_catalogue


def test_summary_prompt_matches_expected_output():
    rendered = get_summary_prompt().render(turns=["human: hello", "ai: hi there"])
    assert (
        rendered
        == "Summarise the following conversation turns concisely:\n\nhuman: hello\nai: hi there"
    )


def test_maestro_system_prompt_uses_the_central_route_catalogue():
    rendered = get_maestro_routing_system_prompt().render(routes=route_catalogue())

    for spec in ROUTE_SPECS:
        assert f"- {spec.name}: {spec.description}" in rendered
    assert "route: the request clearly belongs" in rendered
    assert "clarify:" in rendered
    assert "refuse:" in rendered
    assert "illegal or harmful" in rendered
    assert "savings account" in rendered
    assert "must not be refused" in rendered
    assert "what the advisor can do" in rendered
    assert "without asking for clarification" in rendered
    assert "needs help with money or finances" in rendered
    assert "do not send it to general" in rendered
    assert "untrusted data" in rendered


def test_maestro_human_prompt_keeps_latest_message_separate():
    rendered = get_maestro_routing_human_prompt().render(
        message="How much did I spend?",
        history=None,
    )
    assert rendered == "Latest user message: How much did I spend?"


def test_maestro_human_prompt_includes_recent_context_for_short_answers():
    rendered = get_maestro_routing_human_prompt().render(
        message="growth",
        history="human: How should I invest?\nai: What is your objective?",
    )
    assert "Recent conversation:" in rendered
    assert "What is your objective?" in rendered
    assert rendered.endswith("Latest user message: growth")
