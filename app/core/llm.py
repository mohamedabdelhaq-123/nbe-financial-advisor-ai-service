"""
LLM provider access.

All model access goes through this module so the backing provider stays
configurable: swap OPENAI_BASE_URL/MODEL_NAME to point at OpenAI or a
self-hosted vLLM endpoint with zero code changes. The model is never hardcoded
at a call site.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import settings


@lru_cache(maxsize=None)
def get_chat_model(max_tokens: int | None = None, disable_reasoning: bool = False) -> ChatOpenAI:
    """Return the configured chat model.

    Never called in mock mode — callers short-circuit on
    settings.chat_model.use_mock before reaching a real provider.
    `max_tokens` is an optional output-token ceiling for callers whose response
    shape needs more room than the provider's own default (e.g. a verbose
    structured-output schema repeated across several items) — confirmed
    necessary against a real provider, which otherwise cut a multi-transaction
    structured response off mid-JSON.
    `disable_reasoning` suppresses hidden reasoning tokens on a hybrid
    reasoning model. Per-caller rather than global: a caller doing extraction
    against a fixed schema gains nothing from reasoning but pays its latency,
    while an analysis or planning caller may want it kept.
    """
    return ChatOpenAI(
        base_url=settings.chat_model.openai_base_url,
        model=settings.chat_model.model_name,
        api_key=settings.chat_model.openai_api_key,
        max_tokens=max_tokens,  # type: ignore[call-arg]  # real pydantic field; no mypy plugin configured to see it
        request_timeout=600,  # don't hang indefinitely on slow/queued free-tier LLM calls
        # None leaves the field out of the request entirely, so a provider that
        # rejects "none" (a model whose reasoning is mandatory) is unaffected
        # until a caller opts in.
        reasoning_effort="none" if disable_reasoning else None,
    )
