"""Recommendation request/response schemas."""

from pydantic import BaseModel


class MatchRequest(BaseModel):
    user_id: int
    query: str
    top_k: int = 5


class ProductMatch(BaseModel):
    product_id: int
    product_name: str
    similarity: float


class MatchResponse(BaseModel):
    matches: list[ProductMatch]
