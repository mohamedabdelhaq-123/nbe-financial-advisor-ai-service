"""Unit tests: the scope guardrail's decision logic and fail-open behaviour.

LocalScopeClassifier (real transformers/torch) is deliberately not exercised
here — it needs the optional `local-scope-guard` dependency group, which CI
never installs (see pyproject.toml). HostedScopeClassifier is tested against
a mocked HTTP response, never a real network call.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from structlog.testing import capture_logs

from app.features.chat import scope_guard as scope_guard_module
from app.features.chat.scope_guard import (
    CONTEXT_SNIPPET_CHARS,
    GREETING_LABEL,
    IN_SCOPE_LABEL,
    OUT_OF_SCOPE_LABEL,
    HostedScopeClassifier,
    ScopeResult,
    _is_known_in_scope_phrase,
    _result_from_scores,
    build_scope_check_text,
    check_scope,
)

# ── _result_from_scores: the actual pass/fail decision ──────────────────────


def test_blocks_confident_out_of_scope():
    result = _result_from_scores(OUT_OF_SCOPE_LABEL, 0.9)
    assert result.in_scope is False


def test_allows_confident_in_scope():
    result = _result_from_scores(IN_SCOPE_LABEL, 0.95)
    assert result.in_scope is True


def test_allows_confident_greeting():
    result = _result_from_scores(GREETING_LABEL, 0.93)
    assert result.in_scope is True


def test_fails_open_on_low_confidence_out_of_scope():
    # Below settings.scope_guard.threshold (default 0.55) — an unsure
    # classifier must not refuse a possibly-legitimate question.
    result = _result_from_scores(OUT_OF_SCOPE_LABEL, 0.4)
    assert result.in_scope is True


# ── _is_known_in_scope_phrase / the capability-question bypass ──────────────


@pytest.mark.parametrize(
    "text",
    [
        "what can you help me with?",
        "What Can You Help Me With",
        "so, what can you do exactly",
        "who are you?",
        "ماذا يمكنك أن تفعل؟",
        "من أنت؟",
    ],
)
def test_is_known_in_scope_phrase_matches(text: str):
    assert _is_known_in_scope_phrase(text) is True


@pytest.mark.parametrize(
    "text",
    ["what were my recent transactions?", "write me a poem about the ocean", "hi"],
)
def test_is_known_in_scope_phrase_does_not_overmatch(text: str):
    assert _is_known_in_scope_phrase(text) is False


@pytest.mark.asyncio
async def test_check_scope_bypasses_classifier_for_capability_phrase(monkeypatch):
    monkeypatch.setattr(scope_guard_module.settings.scope_guard, "enabled", True)

    def _fail_if_called():
        raise AssertionError("classifier must not be called for a known capability phrase")

    monkeypatch.setattr(scope_guard_module, "get_scope_classifier", _fail_if_called)

    result = await check_scope("what can you help me with?")
    assert result.in_scope is True


# ── build_scope_check_text: NLI classifier input shaping ────────────────────


def test_build_scope_check_text_empty_messages():
    assert build_scope_check_text([]) == ""


def test_build_scope_check_text_single_message_returns_it_unmodified():
    messages = [HumanMessage(content="what were my recent transactions?")]
    assert build_scope_check_text(messages) == "what were my recent transactions?"


def test_build_scope_check_text_prepends_short_prior_snippet():
    messages = [
        AIMessage(
            content="The category you spent the most on this month is lifestyle, "
            "with a total expense of 400 EGP."
        ),
        HumanMessage(content="what was the description of this transaction?"),
    ]
    text = build_scope_check_text(messages)
    assert text.startswith("The category you spent the most on this month is lifestyle")
    assert text.endswith("what was the description of this transaction?")


def test_build_scope_check_text_truncates_long_prior_message():
    long_prior = "x" * 500
    messages = [AIMessage(content=long_prior), HumanMessage(content="what about this month?")]
    text = build_scope_check_text(messages)
    prefix, _, current = text.rpartition(" what about this month?")
    assert current == ""  # rpartition found the current message at the end
    assert len(prefix) <= CONTEXT_SNIPPET_CHARS


def test_build_scope_check_text_current_message_last_and_untruncated():
    # A genuine topic switch must still dominate the premise — its full text
    # is preserved even though the prior context is capped short.
    messages = [
        AIMessage(content="You spent 1,240 EGP on groceries last month."),
        HumanMessage(content="ok now give me the recipe for shakshoka please, step by step"),
    ]
    text = build_scope_check_text(messages)
    assert text.endswith("ok now give me the recipe for shakshoka please, step by step")


def test_build_scope_check_text_skips_empty_prior_content():
    messages = [AIMessage(content=""), HumanMessage(content="what about this month?")]
    assert build_scope_check_text(messages) == "what about this month?"


def test_build_scope_check_text_non_string_current_content_stringified():
    messages = [HumanMessage(content=[{"type": "text", "text": "hi"}])]
    # Just must not raise — non-string content is stringified, not indexed.
    assert isinstance(build_scope_check_text(messages), str)


# ── check_scope: disabled / fail-open / no-PII-in-logs ───────────────────────


@pytest.mark.asyncio
async def test_check_scope_allows_everything_when_disabled(monkeypatch):
    monkeypatch.setattr(scope_guard_module.settings.scope_guard, "enabled", False)
    result = await check_scope("anything at all")
    assert result.in_scope is True


@pytest.mark.asyncio
async def test_check_scope_fails_open_when_classifier_errors(monkeypatch):
    monkeypatch.setattr(scope_guard_module.settings.scope_guard, "enabled", True)

    class _BrokenClassifier:
        async def classify(self, text: str) -> ScopeResult:
            raise RuntimeError("simulated classifier outage")

    monkeypatch.setattr(scope_guard_module, "get_scope_classifier", lambda: _BrokenClassifier())

    result = await check_scope("what were my recent transactions?")
    assert result.in_scope is True


@pytest.mark.asyncio
async def test_check_scope_logs_outcome_without_the_message_text(monkeypatch):
    monkeypatch.setattr(scope_guard_module.settings.scope_guard, "enabled", True)

    class _BlockingClassifier:
        async def classify(self, text: str) -> ScopeResult:
            return ScopeResult(in_scope=False, top_label=OUT_OF_SCOPE_LABEL, score=0.87)

    monkeypatch.setattr(scope_guard_module, "get_scope_classifier", lambda: _BlockingClassifier())

    secret_message = "write me a poem about my ex, her name is Jane Doe"
    with capture_logs() as entries:
        result = await check_scope(secret_message)

    assert result.in_scope is False
    blocked_events = [e for e in entries if e["event"] == "scope_guard_blocked"]
    assert len(blocked_events) == 1
    logged = blocked_events[0]
    assert logged["top_label"] == OUT_OF_SCOPE_LABEL
    assert logged["score"] == 0.87
    # The whole point: the guard's own logs must not become a new PII leak.
    assert secret_message not in repr(logged)


# ── HostedScopeClassifier: mocked HTTP, never a real network call ──────────


@pytest.mark.asyncio
async def test_hosted_classifier_parses_response(monkeypatch):
    fake_key = MagicMock(get_secret_value=lambda: "test-token")
    monkeypatch.setattr(scope_guard_module.settings.scope_guard, "hosted_api_key", fake_key)

    classifier = HostedScopeClassifier()

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    # Real shape from router.huggingface.co/hf-inference: an array of
    # {label, score} objects sorted highest-first — verified against the
    # live endpoint, not the older api-inference.huggingface.co shape.
    fake_response.json.return_value = [
        {"label": OUT_OF_SCOPE_LABEL, "score": 0.81},
        {"label": IN_SCOPE_LABEL, "score": 0.19},
    ]
    classifier._client.post = AsyncMock(return_value=fake_response)

    result = await classifier.classify("help me write a resignation letter")

    assert result.top_label == OUT_OF_SCOPE_LABEL
    assert result.score == 0.81
    assert result.in_scope is False
    classifier._client.post.assert_awaited_once()
