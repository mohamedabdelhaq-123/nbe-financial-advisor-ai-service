"""Embeddings HTTP contract — request validation plus a hand-written mirror of OpenAI's
embeddings response shape (deliberately not imported from the `openai` SDK; see research.md)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EmbeddingRequest(BaseModel):
    input: list[str] = Field(description="Text(s) to embed.", examples=["hello world"])
    model: str | None = Field(
        default=None,
        description="Accepted for OpenAI-shape compatibility; ignored (single configured model).",
    )
    dimensions: int | None = Field(
        default=None,
        gt=0,
        description="Output vector size. Omit for the configured default.",
    )

    @field_validator("input", mode="before")
    @classmethod
    def _normalize_and_reject_blank(cls, v: str | list[str]) -> list[str]:
        texts = [v] if isinstance(v, str) else v
        texts = [t.strip() for t in texts if t.strip()]
        if not texts:
            raise ValueError("input must contain at least one non-blank string")
        return texts


class EmbeddingDatum(BaseModel):
    object: Literal["embedding"] = "embedding"
    embedding: list[float]
    index: int


class EmbeddingUsage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[EmbeddingDatum]
    model: str
    usage: EmbeddingUsage
