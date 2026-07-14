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
