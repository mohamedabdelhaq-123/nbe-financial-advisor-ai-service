"""Embedding service.

Returns 768-dimensional vectors. In mock mode, returns deterministic vectors.
"""

import hashlib

from app.core.config import settings


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if settings.use_mock_llm:
        return [_mock_vector(t, dim=768) for t in texts]

    raise RuntimeError("Embedding service not configured for real mode")


def _mock_vector(text: str, dim: int = 768) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    result: list[float] = []
    for i in range(dim):
        byte_idx = i % len(h)
        result.append((h[byte_idx] + i) / 255.0)
    norm = sum(v * v for v in result) ** 0.5
    return [v / norm for v in result]
