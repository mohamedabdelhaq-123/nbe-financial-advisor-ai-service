"""Embeddings HTTP surface — OpenAI-embeddings-API-shaped endpoint for the backend."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.core.security import ERROR_RESPONSES, require_token
from app.features.embed.schemas import (
    EmbeddingDatum,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from app.features.embed.service import count_tokens, embed_texts

router = APIRouter(
    prefix="/internal/embeddings", tags=["embed"], dependencies=[Depends(require_token)]
)


@router.post("", response_model=EmbeddingResponse, responses={**ERROR_RESPONSES})
async def create_embeddings(body: EmbeddingRequest):
    """Embed one or more texts. No PII redaction and no audit-log entry (FR-012, FR-013) —
    this is a stateless transformation; text is embedded exactly as submitted."""
    try:
        vectors = await embed_texts(body.input, dimensions=body.dimensions)
    except Exception as exc:
        raise HTTPException(502, detail="Embedding provider unavailable") from exc

    n = count_tokens(body.input, settings.embeddings.model_name)
    return EmbeddingResponse(
        data=[EmbeddingDatum(embedding=v, index=i) for i, v in enumerate(vectors)],
        model=settings.embeddings.model_name,
        usage=EmbeddingUsage(prompt_tokens=n, total_tokens=n),
    )
