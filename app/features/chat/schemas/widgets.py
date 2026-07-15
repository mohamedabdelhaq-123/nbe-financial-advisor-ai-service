"""Widget models — rich payloads that travel with a finalized reply.

A discriminated union keyed on the ``type`` literal so the wire shape is
enforced by the schema, not by convention (per data-model.md §Widget).
"""

from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field


class Allocation(BaseModel):
    """One category slice of a proposed budget allocation."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"category": "Groceries", "percentage": 25.0}]}
    )

    category: str = Field(description="Budget category name.")
    percentage: float = Field(
        ge=0,
        le=100,
        description="Share of total budget allocated to this category, as a percentage (0–100).",
    )


class AllocationSliderPayload(BaseModel):
    """Payload of an `allocation_slider` widget."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "allocations": [
                        {"category": "Groceries", "percentage": 25.0},
                        {"category": "Rent", "percentage": 50.0},
                        {"category": "Savings", "percentage": 25.0},
                    ]
                }
            ]
        }
    )

    allocations: list[Allocation] = Field(
        description="Proposed per-category percentages; SHOULD sum to 100."
    )


class ProductMatchPayloadItem(BaseModel):
    """One matched product entry in a `product_card` widget."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
                    "product_name": "High-Yield Savings",
                    "similarity": 0.92,
                }
            ]
        }
    )

    product_id: UUID4 = Field(description="Stable identifier of the matched product.")
    product_name: str = Field(description="Display name of the matched product.")
    similarity: float = Field(
        ge=0.0,
        le=1.0,
        description="Match similarity score in [0.0, 1.0].",
    )


class ProductCardPayload(BaseModel):
    """Payload of a `product_card` widget."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "products": [
                        {
                            "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
                            "product_name": "High-Yield Savings",
                            "similarity": 0.92,
                        },
                        {
                            "product_id": "9f4b2a1c-2d3e-4f5a-8b7c-1d2e3f4a5b6c",
                            "product_name": "Cashback Card",
                            "similarity": 0.81,
                        },
                    ]
                }
            ]
        }
    )

    products: list[ProductMatchPayloadItem] = Field(description="Matched products (up to top_k=3).")


class AllocationSliderWidget(BaseModel):
    """Widget rendering an adjustable per-category budget allocation."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "allocation_slider",
                    "payload": {
                        "allocations": [
                            {"category": "Groceries", "percentage": 25.0},
                            {"category": "Rent", "percentage": 50.0},
                            {"category": "Savings", "percentage": 25.0},
                        ]
                    },
                }
            ]
        }
    )

    type: Literal["allocation_slider"] = Field(
        default="allocation_slider",
        description="Discriminator; always `allocation_slider`.",
    )
    payload: AllocationSliderPayload = Field(description="The allocation breakdown.")


class ProductCardWidget(BaseModel):
    """Widget rendering a set of matched product cards."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "product_card",
                    "payload": {
                        "products": [
                            {
                                "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
                                "product_name": "High-Yield Savings",
                                "similarity": 0.92,
                            }
                        ]
                    },
                }
            ]
        }
    )

    type: Literal["product_card"] = Field(
        default="product_card",
        description="Discriminator; always `product_card`.",
    )
    payload: ProductCardPayload = Field(description="The matched products.")


Widget = AllocationSliderWidget | ProductCardWidget
