"""Embedding feature service — thin wrapper over the core embedding capability."""

from app.core.config import settings
from app.core.embedding import get_embedding_model
from app.features.embed.cleaning import clean_texts


async def embed_texts(
    texts: list[str], dimensions: int | None = None, clean: bool = True
) -> list[list[float]]:
    """Embed texts, cleaning them first unless the caller has already done so.

    Cleaning defaults on here rather than at each call site so every producer —
    transaction summaries, monthly summaries, seeded problem statements and the
    queries matched against them — is normalized the same way.
    """
    if not texts:
        return []
    if clean:
        texts = clean_texts(texts, max_chars=settings.embeddings.max_input_chars)
    return await get_embedding_model(dimensions=dimensions).aembed_documents(texts)
