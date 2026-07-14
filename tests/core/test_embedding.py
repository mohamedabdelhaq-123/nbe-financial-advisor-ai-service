"""Core embedding service tests — mock-mode determinism, dimension, and cache-key correctness."""

import pytest
from langchain_openai import OpenAIEmbeddings

from app.core.config import settings
from app.core.embedding import get_embedding_model


@pytest.mark.asyncio
async def test_mock_mode_returns_default_dimension_vector():
    model = get_embedding_model()
    vectors = await model.aembed_documents(["hello world"])
    assert len(vectors[0]) == settings.embedding_dimensions == 768


@pytest.mark.asyncio
async def test_mock_mode_is_deterministic():
    model = get_embedding_model()
    v1 = await model.aembed_documents(["same text"])
    v2 = await model.aembed_documents(["same text"])
    v3 = await model.aembed_documents(["different text"])
    assert v1 == v2
    assert v1 != v3


@pytest.mark.asyncio
async def test_custom_dimensions_override():
    model = get_embedding_model(dimensions=256)
    vectors = await model.aembed_documents(["x"])
    assert len(vectors[0]) == 256


def test_mode_flip_after_cache_population_returns_fresh_real_model(monkeypatch):
    """Regression test for the cache-key bug found during /speckit-analyze.

    Calling get_embedding_model() in mock mode first (populating any cache keyed only
    on dimensions), then flipping settings.use_mock_llm to False, must return a fresh
    real-mode model on the next call with the same default dimensions — not a stale
    cached mock instance.
    """
    get_embedding_model()  # populate cache in mock mode with default dimensions first

    monkeypatch.setattr(settings, "use_mock_llm", False)
    monkeypatch.setattr(settings, "embedding_api_key", "sk-test-not-a-placeholder")

    model = get_embedding_model()

    assert isinstance(model, OpenAIEmbeddings)
    assert model.model == settings.embedding_model_name
