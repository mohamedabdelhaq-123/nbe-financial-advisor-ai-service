"""
LLM provider access.

All model access goes through this module so the backing provider stays
configurable: swap OPENAI_BASE_URL/MODEL_NAME to point at OpenAI or a
self-hosted vLLM endpoint with zero code changes. The model is never hardcoded
at a call site.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings


@lru_cache(maxsize=None)
def get_chat_model(max_tokens: int | None = None) -> ChatOpenAI:
    """Return the configured chat model.

    Never called in mock mode — callers short-circuit on settings.use_mock_llm
    before reaching a real provider. `max_tokens` is an optional output-token
    ceiling for callers whose response shape needs more room than the
    provider's own default (e.g. a verbose structured-output schema repeated
    across several items) — confirmed necessary against a real provider,
    which otherwise cut a multi-transaction structured response off mid-JSON.
    """
    return ChatOpenAI(
        base_url=settings.openai_base_url,
        model=settings.model_name,
        api_key=SecretStr(settings.openai_api_key),
        max_tokens=max_tokens,  # type: ignore[call-arg]  # real pydantic field; no mypy plugin configured to see it
    )
