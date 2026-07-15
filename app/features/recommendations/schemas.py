"""Recommendation request/response schemas."""

from pydantic import UUID4, BaseModel, ConfigDict, Field


class MatchRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f",
                    "query": "low-fee savings account",
                    "top_k": 5,
                }
            ]
        }
    )

    user_id: UUID4 = Field(
        description="Backend user ID to find product matches for.",
        examples=["3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f"],
    )
    query: str = Field(
        description="Natural-language description of what the user is looking for.",
        examples=["low-fee savings account"],
    )
    top_k: int = Field(default=5, description="Maximum number of matches to return.", examples=[5])


class ProductMatch(BaseModel):
    product_id: UUID4 = Field(
        description="Backend product ID.", examples=["5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f"]
    )
    product_name: str = Field(
        description="Product display name.", examples=["Premium Savings Account"]
    )
    similarity: float = Field(
        description="Cosine similarity score between the query and the product embedding (0-1).",
        examples=[0.87],
    )


class MatchResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "matches": [
                        {
                            "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
                            "product_name": "Premium Savings Account",
                            "similarity": 0.87,
                        }
                    ]
                }
            ]
        }
    )

    matches: list[ProductMatch] = Field(
        description="Product matches ranked by descending similarity."
    )
