"""Transaction embedding HTTP contract — request validation and response shapes."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MAX_TRANSACTION_EMBED_IDS = 500


class TransactionEmbedRequest(BaseModel):
    transaction_ids: list[UUID] = Field(
        description="Backend transaction IDs to embed.",
        min_length=1,
    )

    @field_validator("transaction_ids", mode="after")
    @classmethod
    def _dedupe_and_check_size(cls, v: list[UUID]) -> list[UUID]:
        # Field(min_length=1) already rejects an empty raw list; deduplicating a
        # non-empty list can never produce an empty one, so only the upper bound
        # needs checking here.
        deduped = list(dict.fromkeys(v))
        if len(deduped) > MAX_TRANSACTION_EMBED_IDS:
            raise ValueError(
                f"transaction_ids must contain between 1 and {MAX_TRANSACTION_EMBED_IDS} IDs"
            )
        return deduped


class TransactionEmbedResult(BaseModel):
    transaction_id: UUID
    status: Literal["embedded"] = "embedded"


class TransactionEmbedResponse(BaseModel):
    results: list[TransactionEmbedResult]
