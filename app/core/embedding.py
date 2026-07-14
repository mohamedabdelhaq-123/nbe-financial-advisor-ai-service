"""
Embedding provider access.

All embedding access goes through this module so the backing provider stays
configurable, mirroring app/core/llm.py's get_chat_model. Mock mode is resolved
inside get_embedding_model() itself (not left to callers to branch on), so
behavior stays consistent across every feature that embeds text.
"""

from functools import lru_cache

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.core.config import settings


@lru_cache(maxsize=None)
def _build_embedding_model(dimensions: int, mock: bool) -> Embeddings:
    """Construct and cache an embedding model for a given (dimensions, mock) pair.

    Keyed on `mock` as well as `dimensions` — a single-key cache (dimensions only)
    would let a stale mock instance survive a settings.use_mock_llm flip, since the
    public get_embedding_model() below is otherwise the only thing re-reading that
    setting on each call.
    """
    if mock:
        return DeterministicFakeEmbedding(size=dimensions)
    return OpenAIEmbeddings(
        base_url=settings.embedding_base_url,
        api_key=SecretStr(settings.embedding_api_key),
        model=settings.embedding_model_name,
        dimensions=dimensions,
        # Without this, OpenAIEmbeddings pre-tokenizes input via tiktoken and sends
        # token-ID arrays instead of raw text (its "length-safe" chunking strategy) —
        # correct for genuine OpenAI models, but many OpenAI-compatible providers
        # (e.g. non-OpenAI models proxied through OpenRouter) reject token-array
        # input outright. Sending raw strings also matches this feature's own
        # no-client-side-limits stance (FR-011/spec Assumptions): an over-length
        # input surfaces as a real provider error instead of being silently chunked.
        check_embedding_ctx_length=False,
    )


def get_embedding_model(dimensions: int | None = None) -> Embeddings:
    """Return the configured embedding model, or a deterministic mock in mock mode.

    `dimensions` defaults to settings.embedding_dimensions when omitted. Always
    re-reads settings.use_mock_llm so a config change is reflected on the very next
    call, never masked by a cached instance built under a previous mode.
    """
    dim = dimensions or settings.embedding_dimensions
    return _build_embedding_model(dim, settings.use_mock_llm)
