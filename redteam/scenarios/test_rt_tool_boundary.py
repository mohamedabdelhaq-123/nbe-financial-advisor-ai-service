""" "Tool" abuse / argument-injection, adapted to this service's real shape.

There is no LLM-driven tool-calling here (see test_rt_cross_user_access.py's
module docstring) — so "tool argument injection" becomes "does the HTTP/
service boundary validate and authorize its arguments independently of
whatever produced them", which is the actually-reachable version of this
category for a service whose every DB argument is server/caller-supplied,
never model-chosen. Phase 4.6's checklist (missing, negative, boundary,
type-confused arguments) applies just as well at that boundary.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.features.chat.agents.analysis import analysis_node
from redteam.fixtures.identities import USER_A_ID


@pytest.mark.redteam(id="RT-006", category="tool_boundary", severity="medium")
async def test_analysis_node_missing_user_id_refuses_without_db_call(monkeypatch):
    """RT-006 — missing required argument.

    Attack input: state with `user_id` absent/None (e.g. a caller that
    forgot it, or an attempt to see what happens without one).
    Expected secure behavior: a safe refusal message, no exception, and no
    backend DB query is attempted at all — a missing identity must never
    fall back to "query everything".
    """
    calls = []

    async def _gen():
        calls.append(True)
        yield None

    monkeypatch.setattr("app.backend_db.get_backend_session", _gen)

    result = await analysis_node(
        {"messages": [], "user_id": None, "user_context": None, "intent": "analysis"}
    )
    assert "messages" in result
    assert not calls, "analysis_node queried the backend DB despite having no user_id"


@pytest.mark.redteam(id="RT-007", category="tool_boundary", severity="low")
async def test_analysis_node_nonexistent_user_returns_no_data_not_error(monkeypatch):
    """RT-007 — boundary value: a well-formed but nonexistent user_id.

    Attack input: a random, unseeded UUID as `user_id`, against a backend
    session that returns zero rows for it.
    Expected secure behavior: a clean "no data" reply, not an unhandled
    exception whose message could leak internals.
    """
    from unittest.mock import AsyncMock, MagicMock

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _gen():
        yield mock_session

    monkeypatch.setattr("app.backend_db.get_backend_session", _gen)

    result = await analysis_node(
        {
            "messages": [],
            "user_id": uuid.uuid4(),  # random, unseeded UUID
            "user_context": None,
            "intent": "analysis",
        }
    )
    content = result["messages"][0].content.lower()
    assert "don't have" in content or "no" in content


@pytest.mark.redteam(id="RT-008", category="tool_boundary", severity="medium")
def test_match_request_rejects_negative_top_k():
    """RT-008 — negative-value argument injection on `top_k`.

    Preconditions: none.
    Attack input: `MatchRequest(user_id=<valid UUID>, query="low-fee savings
    account", top_k=-5)` — `top_k` is the K in top-K product matching.
    Expected secure behavior: rejected at the request-validation layer, the
    same way an out-of-range positive `top_k` already is (`le=3` is set,
    but there is no matching `ge` lower bound in
    app/features/recommendations/schemas.py).
    Failure / current state: no `ge` constraint exists, so `top_k=-5`
    currently validates successfully and would reach `match()`'s
    `.limit(top_k)` unchecked. EXPECTED TO FAIL today — reports a real,
    fixable input-validation gap, not a broken test.
    """
    from app.features.recommendations.schemas import MatchRequest

    try:
        accepted = MatchRequest(user_id=str(USER_A_ID), query="low-fee savings account", top_k=-5)
    except ValidationError:
        return  # secure behavior confirmed
    raise AssertionError(f"top_k=-5 was accepted with no validation error: {accepted!r}")


@pytest.mark.redteam(id="RT-009", category="tool_boundary", severity="medium")
@pytest.mark.parametrize(
    "schema_name",
    ["MonthlySummaryRequest", "AnomalyCheckRequest", "PostIngestionRequest"],
)
def test_analytics_requests_reject_malformed_user_id(schema_name: str):
    """RT-009 — type confusion: analytics schemas type `user_id`/`account_id`
    as plain `str` (app/features/analytics/schemas.py), unlike
    `ChatTurnRequest`/`MatchRequest`, which both use `UUID4`.

    Preconditions: none.
    Attack input: `{schema_name}(user_id="not-a-valid-uuid",
    account_id=<valid UUID>, month="2026-01")`.
    Expected secure behavior: a non-UUID `user_id` is rejected at the
    request-validation layer, consistent with the other schemas in this
    same service.
    Failure / current state: `str` accepts anything, and the unguarded
    `uuid.UUID(user_id)` call inside
    `compute_monthly_summary`/`detect_anomalies` then raises a bare
    `ValueError` deeper in the call stack instead of a clean 422. EXPECTED
    TO FAIL today.
    """
    import app.features.analytics.schemas as schemas_module

    schema = getattr(schemas_module, schema_name)
    try:
        accepted = schema(user_id="not-a-valid-uuid", account_id=str(uuid.uuid4()), month="2026-01")
    except ValidationError:
        return  # secure behavior confirmed
    raise AssertionError(
        f"{schema_name}(user_id='not-a-valid-uuid', ...) was accepted with no "
        f"validation error: {accepted!r}"
    )


@pytest.mark.redteam(id="RT-010", category="tool_boundary", severity="low")
def test_transaction_embed_request_enforces_id_count_bounds():
    """RT-010 — positive control: `/internal/transactions/embed` DOES bound
    its argument count (min 1, max 500, deduplicated) — confirms the
    pattern RT-008/RT-009 are missing elsewhere in the service actually
    works where it's applied.

    Attack input: an empty `transaction_ids` list, and separately a list of
    501 unique UUIDs (one over `MAX_TRANSACTION_EMBED_IDS`).
    Expected secure behavior: both rejected at the request-validation layer.
    """
    from app.features.transactions.schemas import (
        MAX_TRANSACTION_EMBED_IDS,
        TransactionEmbedRequest,
    )

    with pytest.raises(ValidationError):
        TransactionEmbedRequest(transaction_ids=[])

    with pytest.raises(ValidationError):
        TransactionEmbedRequest(
            transaction_ids=[uuid.uuid4() for _ in range(MAX_TRANSACTION_EMBED_IDS + 1)]
        )


@pytest.mark.redteam(id="RT-011", category="tool_boundary", severity="low")
def test_chat_request_rejects_malformed_user_id_over_http(client, auth_headers):
    """RT-011 — positive control: the chat endpoint DOES type `user_id` as
    `UUID4` and rejects a malformed one at the HTTP layer with 422, never
    reaching the graph.

    Attack input: `POST /internal/chat` with `user_id: "not-a-uuid-at-all"`.
    Expected secure behavior: HTTP 422, request body rejected before any
    graph/DB work starts.
    """
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c-boundary-test",
            "user_id": "not-a-uuid-at-all",
            "message": "hi",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
