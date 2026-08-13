"""A recording chat-model double for the real (non-mock) LLM code path.

`USE_MOCK_LLM=1` (this whole suite's default) short-circuits every agent
before it ever builds a prompt — which means mock mode can't be used to
answer "what does the prompt sent to the model actually look like, and is
untrusted data role-separated from instructions?". This double stands in
for `app.core.llm.get_chat_model()` so that question is answerable
deterministically, with no network call and no API key: every call site's
real prompt-construction code runs exactly as it does in production, and
`ainvoke`'s argument is simply recorded instead of sent anywhere.
"""

from types import SimpleNamespace
from typing import Any


class _RecordingLLM:
    """Stands in for the `ChatOpenAI` instance `get_chat_model()` returns.

    Supports the three calling shapes used across the codebase:
    `.ainvoke(str_or_messages)` (chat agents, maestro, planner, summarizer)
    and `.with_structured_output(Schema).with_retry(...).ainvoke(...)`
    (statement normalization).
    """

    def __init__(
        self,
        calls: list[Any],
        *,
        content: str = "mock response",
        structured_response: Any = None,
    ) -> None:
        self._calls = calls
        self._content = content
        self._structured_response = structured_response

    async def ainvoke(self, input_: Any, *args: Any, **kwargs: Any) -> Any:
        self._calls.append(input_)
        if self._structured_response is not None:
            return self._structured_response
        return SimpleNamespace(content=self._content)

    def with_structured_output(self, _schema: Any) -> "_RecordingLLM":
        return self

    def with_retry(self, *args: Any, **kwargs: Any) -> "_RecordingLLM":
        return self


def install_fake_chat_model(
    monkeypatch: Any,
    *,
    content: str = "mock response",
    structured_response: Any = None,
) -> list[Any]:
    """Patch `app.core.llm.get_chat_model` to return a recording double.

    Returns the (initially empty) list the double appends every `ainvoke`
    argument to, in call order — inspect it after exercising the code path
    under test. Every call site imports `get_chat_model` lazily
    (`from app.core.llm import get_chat_model` inside the function body),
    so patching the module attribute is picked up on the next call.
    """
    calls: list[Any] = []
    fake = _RecordingLLM(calls, content=content, structured_response=structured_response)
    monkeypatch.setattr("app.core.llm.get_chat_model", lambda *a, **k: fake)
    return calls


def format_prompt(call_arg: Any) -> str:
    """Render an `ainvoke(...)` call argument as plain text for a findings
    report — either shape actually used across this codebase: a bare
    string (no role separation — the prompt *is* this string verbatim), or
    a list of LangChain messages (`[SystemMessage(...), HumanMessage(...)]`)."""
    if isinstance(call_arg, str):
        return call_arg
    try:
        return "\n".join(f"[{m.type}] {m.content}" for m in call_arg)
    except (TypeError, AttributeError):
        return repr(call_arg)


class _PassthroughProxy:
    """Wraps the REAL model returned by `get_chat_model()`: every call still
    reaches the real provider (unlike `_RecordingLLM`), but the argument is
    also recorded first — how `redteam/scenarios/test_rt_real_model_attacks.py`
    captures the exact prompt a real completion was generated from."""

    def __init__(self, real: Any, calls: list[Any]) -> None:
        self._real = real
        self._calls = calls

    async def ainvoke(self, input_: Any, *args: Any, **kwargs: Any) -> Any:
        self._calls.append(input_)
        return await self._real.ainvoke(input_, *args, **kwargs)

    def with_structured_output(self, schema: Any) -> "_PassthroughProxy":
        return _PassthroughProxy(self._real.with_structured_output(schema), self._calls)

    def with_retry(self, *args: Any, **kwargs: Any) -> "_PassthroughProxy":
        return _PassthroughProxy(self._real.with_retry(*args, **kwargs), self._calls)


def install_passthrough_recorder(monkeypatch: Any) -> list[Any]:
    """Patch `app.core.llm.get_chat_model` to return a recording proxy
    around the REAL model — genuine network calls, real completions, with
    the exact prompt captured on the way through. Requires real provider
    credentials (`AI_SERVICE_CHAT_MODEL__*`); pair with
    `force_real_llm_path` so the call site's real (non-mock) branch runs at
    all."""
    from app.core.llm import get_chat_model as real_get_chat_model

    calls: list[Any] = []

    def _factory(*args: Any, **kwargs: Any) -> _PassthroughProxy:
        return _PassthroughProxy(real_get_chat_model(*args, **kwargs), calls)

    monkeypatch.setattr("app.core.llm.get_chat_model", _factory)
    return calls


def force_real_llm_path(monkeypatch: Any) -> None:
    """Flip `settings.chat_model.use_mock` off so agent code takes its real
    (non-mock) branch — the one that actually builds a prompt and calls
    `get_chat_model()` — without needing real provider credentials, since
    `install_fake_chat_model` intercepts the call before any network I/O."""
    from app.core.config import settings

    monkeypatch.setattr(settings.chat_model, "use_mock", False)
