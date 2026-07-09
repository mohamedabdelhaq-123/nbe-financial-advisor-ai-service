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


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """Return the configured chat model.

    Never called in mock mode — callers short-circuit on settings.use_mock_llm
    before reaching a real provider.
    """
    return ChatOpenAI(
        base_url=settings.openai_base_url,
        model=settings.model_name,
        api_key=SecretStr(settings.openai_api_key),
    )
