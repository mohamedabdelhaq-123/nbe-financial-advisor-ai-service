"""Unit tests: the scope guardrail's decision logic and fail-open behaviour.

LocalScopeClassifier (real transformers/torch) is deliberately not exercised
here — it needs the optional `local-scope-guard` dependency group, which CI
never installs (see pyproject.toml). HostedScopeClassifier is tested against
a mocked HTTP response, never a real network call.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.testing import capture_logs

from app.features.chat import scope_guard as scope_guard_module
from app.features.chat.scope_guard import (
    GREETING_LABEL,
    IN_SCOPE_LABEL,
    OUT_OF_SCOPE_LABEL,
    HostedScopeClassifier,
    ScopeResult,
    _is_known_in_scope_phrase,
    _result_from_scores,
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
