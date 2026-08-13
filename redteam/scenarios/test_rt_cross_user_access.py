"""Cross-user data access — the highest-priority category for this service.

Architecture note (see redteam/README.md for the full writeup): this AI
service has no LLM-driven tool-calling surface at all (confirmed by
exhaustive grep — no `bind_tools`/`ToolNode`/`@tool`/`create_react_agent`
anywhere in `app/`). Every DB query a node issues uses a server-controlled
`user_id`/`account_id`, never an LLM-produced argument. That eliminates the
"LLM tricked into calling a tool with someone else's ID" risk class, but it
concentrates the entire cross-user boundary into two narrower, more
consequential questions this file tests directly:

  1. Given a `user_id`, does the query the code actually issues filter by
     it? (RT-001/RT-002/RT-004 — this holds today; positive controls.)
  2. Does anything independently verify that a caller is allowed to *use*
     the `user_id`/`conversation_id` it supplied in the first place? (RT-003/
     RT-005 — per SECURITY_AUDIT_REPORT.md SEC-005, nothing does; both of
     these are EXPECTED TO FAIL today and are the framework correctly
     reporting a real, already-known finding, not a broken test.)
"""

import uuid

import pytest

from app.features.analytics.jobs.anomaly_detection import detect_anomalies
from app.features.analytics.jobs.monthly_summary import compute_monthly_summary
from app.features.chat.agents.analysis import analysis_node
from redteam.assertions.security import assert_no_marker_leak, assert_query_scoped_to
from redteam.fixtures.identities import (
    USER_A_ID,
    USER_A_MARKER,
    USER_B_ID,
    USER_B_MARKER,
)
from redteam.fixtures.transactions import (
    backend_session_gen_for,
    cm_backend_session_gen_for,
    user_a_transactions,
    user_b_transactions,
)

# Not `pytestmark = pytest.mark.asyncio`: `asyncio_mode = "auto"`
# (pyproject.toml) already collects every `async def` test here without it,
# and this file also has one plain `def` test (RT-005) that a blanket marker
# would incorrectly tag.


@pytest.mark.redteam(id="RT-001", category="cross_user_access", severity="critical")
async def test_analysis_node_never_returns_other_users_transactions(monkeypatch):
    """RT-001 — analysis_node must never surface another user's transactions.

    Preconditions: backend DB holds transactions for both User A and User B,
    each tagged with a unique marker (ALPHA.../BETA...).
    Attack input: call `analysis_node` as User A against a session that (as
    a correctly-scoped Postgres query would) returns only User A's rows,
    then as User B against a session returning only User B's rows.
    Expected secure behavior: User A's reply/references never contain
    USER_B_MARKER and vice versa — including across sequential calls in the
    same process (rules out cross-request state bleed via caching/globals).
    Security assertion: substring check on the finalized reply text.
    """
    gen_a, _ = backend_session_gen_for(user_a_transactions())
    monkeypatch.setattr("app.backend_db.get_backend_session", gen_a)
    result_a = await analysis_node(
        {"messages": [], "user_id": USER_A_ID, "user_context": None, "intent": "analysis"}
    )
    text_a = result_a["messages"][0].content
    assert USER_A_MARKER in text_a, "sanity check: User A's own data should be present"
    assert_no_marker_leak(text_a, forbidden=[USER_B_MARKER], context="analysis_node, User A")

    gen_b, _ = backend_session_gen_for(user_b_transactions())
    monkeypatch.setattr("app.backend_db.get_backend_session", gen_b)
    result_b = await analysis_node(
        {"messages": [], "user_id": USER_B_ID, "user_context": None, "intent": "analysis"}
    )
    text_b = result_b["messages"][0].content
    assert USER_B_MARKER in text_b, "sanity check: User B's own data should be present"
    assert_no_marker_leak(text_b, forbidden=[USER_A_MARKER], context="analysis_node, User B")


@pytest.mark.redteam(id="RT-002", category="cross_user_access", severity="critical")
async def test_analysis_node_query_is_structurally_scoped_to_requesting_user(monkeypatch):
    """RT-002 — the SQL the analysis agent issues must filter by the exact
    requesting user's ID, independent of whatever rows a (possibly
    misconfigured) database happens to hand back.

    Attack input: call `analysis_node` for User A and inspect the compiled
    `select(Transaction)...` statement it actually executed.
    Expected secure behavior: the compiled WHERE clause binds
    `transactions.user_id = <User A's UUID>` — not User B's, not unscoped.
    Security assertion: structural inspection of the SQLAlchemy statement,
    not of the returned data (Phase 7: assert at the application layer).
    """
    gen, session = backend_session_gen_for(user_a_transactions())
    monkeypatch.setattr("app.backend_db.get_backend_session", gen)

    await analysis_node(
        {"messages": [], "user_id": USER_A_ID, "user_context": None, "intent": "analysis"}
    )

    assert len(session.executed_statements) == 1
    assert_query_scoped_to(
        session.executed_statements[0], column_repr="transactions.user_id", value=USER_A_ID
    )


@pytest.mark.redteam(id="RT-003", category="cross_user_access", severity="critical")
async def test_conversation_id_reuse_across_users_does_not_leak_context(monkeypatch):
    """RT-003 — SEC-005 regression test (see SECURITY_AUDIT_REPORT.md).

    Preconditions: a real LangGraph Postgres checkpointer (Testcontainers —
    skipped if Docker is unavailable, matching
    tests/integration/test_chat_memory.py's own gating).
    Attack input: User A has an established conversation thread with
    `user_context` containing USER_A_MARKER. A second request reuses the
    *same* `conversation_id` but supplies User B's `user_id`, with no
    `initial_context` of its own — the exact shape of an attacker (or a
    buggy caller) who has learned another user's conversation_id.
    Expected secure behavior: the service does not silently resume User A's
    persisted `user_context`/`planner_answers` under User B's identity —
    either it's rejected, or the inherited context is not User A's.
    Failure: `service.py::stream_chat` trusts `request.user_id`/
    `conversation_id` from the request body with no ownership check
    (confirmed: `app/features/chat/service.py` never queries
    `app.backend_db.models.Conversation` to verify the thread belongs to the
    calling user), so this is EXPECTED TO FAIL today — that failure *is* the
    report of SEC-005, not a broken test. Do not "fix" this test to pass
    without the underlying code fix (an independent ownership check).
    """
    from shutil import which

    if which("docker") is None:
        pytest.skip("Docker not available")

    from testcontainers.postgres import PostgresContainer

    from app.core.config import settings

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        # Mutate the existing `settings` singleton in place rather than
        # `importlib.reload`-ing `app.core.config`: every other module did
        # `from app.core.config import settings` at import time, so a reload
        # would silently strand them on a stale object — this monkeypatch
        # form is what every other scenario in this suite uses, and
        # monkeypatch reverts it cleanly after this test either way.
        monkeypatch.setattr(settings.own_db, "postgres_host", pg.get_container_host_ip())
        monkeypatch.setattr(settings.own_db, "postgres_port", str(pg.get_exposed_port(5432)))
        monkeypatch.setattr(settings.own_db, "postgres_db", pg.dbname)
        monkeypatch.setattr(settings.own_db, "postgres_user", pg.username)
        from pydantic import SecretStr

        monkeypatch.setattr(settings.own_db, "postgres_password", SecretStr(pg.password))

        from app.features.chat.checkpointer import build_checkpointer, setup_checkpointer
        from app.features.chat.graph import build_graph

        saver = await build_checkpointer()
        await setup_checkpointer(saver)
        try:
            graph = build_graph(checkpointer=saver)
            shared_conversation_id = "shared-thread-attacker-guessed"
            config_dict = {"configurable": {"thread_id": shared_conversation_id}}

            # Turn 1: User A establishes context on this thread.
            await graph.ainvoke(
                {
                    "messages": [],
                    "user_id": USER_A_ID,
                    "user_context": {"note": USER_A_MARKER},
                    "stage": "",
                    "intent": "",
                    "planner_answers": {},
                    "questions_asked": 0,
                    "message_references": [],
                },
                config_dict,
            )

            # Turn 2: same thread_id, User B's identity, no initial_context of
            # their own — mirrors ChatTurnRequest.initial_context=None falling
            # back to prev_values.get("user_context") in service.py.
            snapshot = await graph.aget_state(config_dict)
            prev_values = snapshot.values if snapshot else {}
            inherited_context = prev_values.get("user_context")

            assert inherited_context is None or USER_A_MARKER not in str(inherited_context), (
                "SEC-005: conversation_id reuse across different user_id values leaked "
                f"User A's context into what should be User B's turn: {inherited_context!r}"
            )
        finally:
            await saver.conn.close()


@pytest.mark.redteam(id="RT-004", category="cross_user_access", severity="high")
async def test_analytics_jobs_are_structurally_scoped_to_user_and_account(monkeypatch):
    """RT-004 — positive control: the deterministic analytics pipelines
    (monthly summary, anomaly detection) filter by BOTH user_id and
    account_id, not just one, at the SQL layer.

    Attack input: none — inspects the compiled `select(Transaction)...`
    statements `compute_monthly_summary`/`detect_anomalies` actually issue
    for a given user_id/account_id pair.
    Expected secure behavior: both compiled queries bind the exact
    user_id/account_id passed in. This passes today — included so a future
    change that weakens either filter is caught immediately.
    """
    account_id = uuid.uuid4()
    gen, summary_session = cm_backend_session_gen_for(user_a_transactions())
    await compute_monthly_summary(
        session_gen=gen,
        embed_fn=_fake_embed,
        user_id=str(USER_A_ID),
        account_id=str(account_id),
        month="2026-01",
    )
    assert_query_scoped_to(
        summary_session.executed_statements[0],
        column_repr="transactions.user_id",
        value=USER_A_ID,
    )
    assert_query_scoped_to(
        summary_session.executed_statements[0],
        column_repr="transactions.account_id",
        value=account_id,
    )

    gen2, anomaly_session = cm_backend_session_gen_for(user_a_transactions())
    await detect_anomalies(
        session_gen=gen2, user_id=str(USER_A_ID), account_id=str(account_id), month="2026-01"
    )
    assert_query_scoped_to(
        anomaly_session.executed_statements[0],
        column_repr="transactions.user_id",
        value=USER_A_ID,
    )
    assert_query_scoped_to(
        anomaly_session.executed_statements[0],
        column_repr="transactions.account_id",
        value=account_id,
    )


async def _fake_embed(texts: list[str], dimensions: int | None = None) -> list[list[float]]:
    return [[0.0] * (dimensions or 8) for _ in texts]


@pytest.mark.redteam(id="RT-005", category="cross_user_access", severity="critical")
def test_chat_service_never_verifies_conversation_ownership_before_trusting_request():
    """RT-005 — static companion to RT-003, runs with no Docker dependency.

    Attack input: none — this inspects `stream_chat`'s own source.
    Expected secure behavior: before trusting `request.user_id` as the
    identity for a `conversation_id` it didn't mint, the service looks up
    that conversation's real owner via the read-only backend mirror
    (`app.backend_db.models.Conversation`, which already exists and is
    already used read-only elsewhere in this codebase) and rejects a
    mismatch.
    Failure / current state: no such lookup exists anywhere in
    `app/features/chat/service.py` — `request.user_id` and
    `request.conversation_id` are used directly. EXPECTED TO FAIL today;
    this is SEC-005 (SECURITY_AUDIT_REPORT.md), reported by the framework,
    not a bug in the test.
    """
    import inspect

    from app.features.chat import service

    source = inspect.getsource(service)
    assert "Conversation" in source, (
        "app/features/chat/service.py never cross-checks request.conversation_id's real "
        "owner (via app.backend_db.models.Conversation) against request.user_id before "
        "trusting either — SEC-005. See RT-003 for the behavioral version of this test."
    )
