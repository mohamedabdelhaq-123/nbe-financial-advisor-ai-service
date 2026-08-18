"""Secrets / internal-detail exfiltration via error paths and logging.

RT-019 confirms the ingestion error path no longer echoes raw exception text
unredacted (fixed — see process.py), matching RT-020's chat error path,
which deliberately never did (FR-010, already a positive control worth
regression-testing).
"""

import uuid

import pytest

from app.core.config import settings


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self) -> bytes:
        return self._data


class _FakeStatement:
    def __init__(self, seaweed_file_id: str) -> None:
        self.seaweed_file_id = seaweed_file_id


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeBackendSession:
    def __init__(self, row) -> None:
        self._row = row

    async def execute(self, stmt):
        return _FakeResult(self._row)


class _FailingStorage:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, *exc):
        return False


@pytest.mark.redteam(id="RT-019", category="secrets_exfiltration", severity="high")
@pytest.mark.asyncio
async def test_ingestion_process_error_does_not_echo_secret_bearing_exception_text(monkeypatch):
    """RT-019 — ingestion error responses must never echo raw internal
    exception text that could carry a secret.

    Attack input: none required from an attacker — this simulates a
    storage-layer failure whose exception message happens to embed the
    service's own configured token (a realistic shape for, e.g., a
    connection-string-bearing driver error).
    Expected secure behavior: the `HTTPException.detail` returned to the
    caller never contains the real secret value, regardless of what the
    underlying exception says. Fixed:
    `app/features/ingestion/service/process.py::process_statement` now logs
    the real exception server-side and returns a generic detail message,
    instead of interpolating the raw exception into the response.
    """
    from app.features.ingestion.service.process import process_statement

    real_token = settings.token.get_secret_value()
    statement_id = str(uuid.uuid4())
    row = _FakeStatement(seaweed_file_id="bucket/key.pdf")

    async def session_gen():
        yield _FakeBackendSession(row)

    async def own_session_gen():
        yield _FakeBackendSession(None)

    leaking_exc = ConnectionError(f"upstream refused connection (token={real_token})")
    monkeypatch.setattr(
        "app.features.ingestion.service.process.get_storage_backend",
        lambda: _FailingStorage(leaking_exc),
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await process_statement(
            session_gen=session_gen, own_session_gen=own_session_gen, statement_id=statement_id
        )

    assert real_token not in str(exc_info.value.detail), (
        "ingestion error response echoed the real configured secret token verbatim: "
        f"{exc_info.value.detail!r}"
    )


@pytest.mark.redteam(id="RT-020", category="secrets_exfiltration", severity="high")
@pytest.mark.asyncio
async def test_chat_stream_error_never_leaks_exception_details(monkeypatch):
    """RT-020 — positive control: the chat SSE error path is generic by
    design (FR-010, `app/features/chat/service.py::stream_chat`'s except
    block).

    Attack input: none from an attacker — this forces the graph to raise
    `RuntimeError(f"db connection failed: password={secret}")`, simulating
    a real internal failure whose message happens to embed a secret.
    Expected secure behavior: the SSE `error` event's message is always the
    fixed string "Something went wrong. Please try again." — the real
    exception (and any secret in it) is logged server-side only, never sent
    to the client.
    """
    from app.features.chat.schemas import ChatTurnRequest
    from app.features.chat.service import stream_chat

    monkeypatch.setattr(settings.chat_model, "use_mock", False)

    class _ExplodingCheckpointer:
        pass

    class _App:
        class state:
            checkpointer = _ExplodingCheckpointer()

    secret_value = "sk-super-secret-db-password-should-never-egress"

    class _ExplodingGraph:
        async def aget_state(self, config):
            return None

        def astream(self, *a, **k):
            async def _gen():
                raise RuntimeError(f"db connection failed: password={secret_value}")
                yield  # pragma: no cover - unreachable, makes this an async generator

            return _gen()

    monkeypatch.setattr(
        "app.features.chat.graph.build_graph", lambda checkpointer=None: _ExplodingGraph()
    )

    class _FailingOwnSession:
        async def __aenter__(self):
            raise RuntimeError("own DB unreachable in this test double, by design")

        async def __aexit__(self, *exc):
            return False

    # Audit-write is best-effort (try/except Exception: pass at the end of
    # stream_chat) — fail it fast and deterministically rather than letting
    # a real DNS/connection attempt to the placeholder own-DB host run.
    monkeypatch.setattr("app.core.db.OwnSession", lambda: _FailingOwnSession())

    request = ChatTurnRequest(
        conversation_id="c-secret-leak-test", user_id=uuid.uuid4(), message="hi"
    )

    frames = [chunk async for chunk in stream_chat(_App(), request)]
    body = "".join(frames)

    assert secret_value not in body, f"secret leaked into the SSE body: {body!r}"
    assert '"event": "error"' in body or '"event":"error"' in body, f"no error event: {body!r}"
    assert "Something went wrong" in body, f"actual SSE body sent to client: {body!r}"


@pytest.mark.redteam(id="RT-021", category="secrets_exfiltration", severity="medium")
def test_raw_content_logging_is_off_by_default(monkeypatch):
    """RT-021 — `raw_content_fields()` (app/core/logging.py) is the required
    call site for any log line carrying raw LLM prompt/completion or DB
    query content (FR-011: default-off, explicit opt-in).

    Attack input: `raw_content_fields(prompt="how much did I spend, "
    "ALPHA-USER-A-SECRET")` with `debug_include_raw_content=False`, then
    the same call with it `True`.
    Expected secure behavior: with `debug_include_raw_content=False` (the
    default), it returns an empty dict — a financial-chat prompt passed
    through it never reaches a log line — and returns the real fields only
    when explicitly enabled.
    """
    from app.core.config import settings as cfg
    from app.core.logging import raw_content_fields

    monkeypatch.setattr(cfg.logging, "debug_include_raw_content", False)
    assert raw_content_fields(prompt="how much did I spend, ALPHA-USER-A-SECRET") == {}

    monkeypatch.setattr(cfg.logging, "debug_include_raw_content", True)
    assert raw_content_fields(prompt="x") == {"prompt": "x"}
