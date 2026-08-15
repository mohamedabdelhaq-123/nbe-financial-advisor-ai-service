"""Security assertion helpers shared across scenario modules."""

from typing import Any


def assert_no_marker_leak(text: str, *, forbidden: list[str], context: str = "") -> None:
    """Fail if any `forbidden` marker string appears in `text`.

    The core cross-user assertion: `forbidden` is the *other* user's secret
    marker(s) (see `redteam/fixtures/identities.py`), so this is a plain
    substring check, not a judgment call about what "looks like a leak".
    """
    lowered = text.lower()
    leaked = [m for m in forbidden if m.lower() in lowered]
    assert not leaked, (
        f"Cross-user/secret leak{f' ({context})' if context else ''}: "
        f"found {leaked!r} in response text: {text!r}"
    )


def assert_role_separated_call(call_arg: Any, *, completion: Any = None) -> list[Any]:
    """Assert an `ainvoke(...)` call argument is a list of role-tagged
    messages (`SystemMessage`/`HumanMessage`/...), not one bare string —
    i.e. the call site used LangChain's role-separation mechanism at all.

    Returns the message list for further inspection on success. This is the
    single most load-bearing structural check in the instruction-hierarchy
    category: a bare string concatenating instructions and untrusted data
    has no role boundary for the model to respect in the first place,
    regardless of how careful the wording is.

    `completion` is optional and purely for the failure message: pass the
    value the test's fake chat model was configured to return (see
    `redteam/runners/fake_llm.py`) so a finding shows the full exchange —
    the exact prompt sent AND what came back — not just the prompt half.
    """
    completion_note = f"\nCompletion returned: {completion!r}" if completion is not None else ""
    assert isinstance(call_arg, list), (
        "Expected a role-separated message list (e.g. [SystemMessage(...), "
        f"HumanMessage(...)]), got a bare {type(call_arg).__name__} — the exact prompt "
        f"sent to the model: {call_arg!r}{completion_note}"
    )
    from langchain_core.messages import BaseMessage

    assert all(isinstance(m, BaseMessage) for m in call_arg), (
        f"Expected every item to be a LangChain message, got: "
        f"{[type(m) for m in call_arg]}{completion_note}"
    )
    return call_arg


def assert_system_message_unmodified(messages: list[Any], expected_system_text: str) -> None:
    """Assert exactly one `SystemMessage` is present and its content is
    byte-for-byte the application's own constant — i.e. nothing in the
    conversation (including a fake "SYSTEM:" line smuggled in via user
    text) altered, appended to, or replaced the real system instructions."""
    from langchain_core.messages import SystemMessage

    system_messages = [m for m in messages if isinstance(m, SystemMessage)]
    assert (
        len(system_messages) == 1
    ), f"Expected exactly one SystemMessage, found {len(system_messages)}: {messages!r}"
    assert system_messages[0].content == expected_system_text, (
        "System prompt content was altered — expected the application's own constant, got: "
        f"{system_messages[0].content!r}"
    )


def where_clause_sql(statement: Any) -> str:
    """Render a SQLAlchemy `Select`'s compiled WHERE clause (with bound
    literal values inlined) for structural inspection — lets a test assert
    "this query is scoped to user X" without standing up a real database.

    Compiled against the PostgreSQL dialect explicitly (matching this
    service's real backend and own databases) — the generic/default dialect
    does not reliably literal-render every column type these models use
    (e.g. `Uuid`).
    """
    from sqlalchemy.dialects import postgresql

    compiled = statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return str(compiled)


def assert_query_scoped_to(statement: Any, *, column_repr: str, value: Any) -> None:
    """Assert a compiled SELECT's WHERE clause includes `column = value`
    (as substrings of the literal-bound SQL) — the deterministic,
    no-database way to confirm a query is actually scoped to one user/
    account rather than trusting the returned rows alone."""
    sql = where_clause_sql(statement)
    needle = str(value)
    assert column_repr in sql, f"Expected {column_repr!r} in compiled WHERE clause: {sql}"
    assert needle in sql, f"Expected bound value {needle!r} in compiled WHERE clause: {sql}"
