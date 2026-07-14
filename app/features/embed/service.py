"""Embedding feature service — thin wrapper over the core embedding capability."""

import tiktoken

from app.core.embedding import get_embedding_model


async def embed_texts(texts: list[str], dimensions: int | None = None) -> list[list[float]]:
    if not texts:
        return []
    return await get_embedding_model(dimensions=dimensions).aembed_documents(texts)


def count_tokens(texts: list[str], model: str) -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return sum(len(encoding.encode(t)) for t in texts)
