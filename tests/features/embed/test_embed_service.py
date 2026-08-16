"""Embedding feature service tests — embed_texts() wraps the core service correctly."""

import ast
from pathlib import Path

import pytest

from app.features.embed.service import embed_texts


@pytest.mark.asyncio
async def test_embed_texts_returns_ordered_vectors():
    vectors = await embed_texts(["a", "b"])
    assert len(vectors) == 2
    assert vectors[0] != vectors[1]


@pytest.mark.asyncio
async def test_embed_texts_empty_list_returns_empty():
    assert await embed_texts([]) == []


@pytest.mark.asyncio
async def test_embed_texts_dimensions_forwarded():
    vectors = await embed_texts(["x"], dimensions=256)
    assert len(vectors[0]) == 256


@pytest.mark.asyncio
async def test_embed_texts_cleans_by_default():
    # Same text, differing only in OCR noise — the mock is deterministic per string,
    # so identical vectors prove the two inputs converged before embedding.
    noisy, clean = "كارفور‏  الـــقاهرة  ٢٥٠", "كارفور القاهرة 250"
    vectors = await embed_texts([noisy, clean])
    assert vectors[0] == vectors[1]


@pytest.mark.asyncio
async def test_embed_texts_clean_false_embeds_verbatim():
    noisy, clean = "كارفور‏  الـــقاهرة  ٢٥٠", "كارفور القاهرة 250"
    vectors = await embed_texts([noisy, clean], clean=False)
    assert vectors[0] != vectors[1]


@pytest.mark.asyncio
async def test_embed_texts_respects_max_input_chars(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings.embeddings, "max_input_chars", 5)
    truncated, full = await embed_texts(["abcde", "abcdefghij"])
    assert truncated == full


def test_no_hand_rolled_hashlib_mock_remains():
    source = Path("app/features/embed/service.py").read_text()
    tree = ast.parse(source)
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "hashlib" not in imported_names
