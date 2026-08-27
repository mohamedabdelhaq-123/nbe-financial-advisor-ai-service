"""Widget models — rich payloads that travel with a finalized reply.

A discriminated union keyed on the ``type`` literal so the wire shape is
enforced by the schema, not by convention (per data-model.md §Widget).
"""

import datetime
from typing import Annotated, Literal

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


class CategorySpend(BaseModel):
    """One category slice of a spending breakdown."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"name": "groceries", "amount": 1240.5, "pct": 31.2}]}
    )

    name: str = Field(
        description="Backend category name, as returned by the backend's category list."
    )
    amount: float = Field(ge=0, description="Total spent in this category, in `currency`.")
    pct: float = Field(
        ge=0,
        le=100,
        description="Share of the period's total spend, as a percentage (0–100).",
    )


class SpendingBreakdownPayload(BaseModel):
    """Payload of a `spending_breakdown` widget."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "currency": "EGP",
                    "month": "July 2026",
                    "total": 3975.0,
                    "categories": [
                        {"name": "groceries", "amount": 1240.5, "pct": 31.2},
                        {"name": "housing", "amount": 2000.0, "pct": 50.3},
                        {"name": "transport", "amount": 734.5, "pct": 18.5},
                    ],
                }
            ]
        }
    )

    currency: str = Field(description="ISO currency code every amount is denominated in.")
    month: str = Field(description='Display label for the period, e.g. "July 2026".')
    total: float = Field(ge=0, description="Total spend across all categories, in `currency`.")
    categories: list[CategorySpend] = Field(
        description="Per-category spend, highest first; percentages SHOULD sum to ~100."
    )


class TransactionListItem(BaseModel):
    """One row of a `transactions_list` widget."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "b3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
                    "title": "Carrefour",
                    "category": "groceries",
                    "type": "expense",
                    "amount": 340.25,
                    "date": "2026-07-14",
                }
            ]
        }
    )

    id: UUID4 = Field(description="Backend transaction identifier.")
    title: str = Field(description="Display title — the normalized or raw merchant name.")
    category: str = Field(description="Backend category name, or `uncategorized`.")
    type: Literal["income", "expense"] = Field(
        description=(
            "Direction as the app presents it: `income` for credit rows, `expense` for "
            "debit, fee, and transfer rows."
        )
    )
    amount: float = Field(ge=0, description="Unsigned magnitude; direction comes from `type`.")
    date: datetime.date = Field(
        description=(
            "Transaction date (ISO `YYYY-MM-DD`). The backend stores a date only — there "
            "is no time-of-day for a transaction."
        )
    )


class TransactionsListPayload(BaseModel):
    """Payload of a `transactions_list` widget."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "currency": "EGP",
                    "transactions": [
                        {
                            "id": "b3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
                            "title": "Carrefour",
                            "category": "groceries",
                            "type": "expense",
                            "amount": 340.25,
                            "date": "2026-07-14",
                        }
                    ],
                }
            ]
        }
    )

    currency: str = Field(description="ISO currency code every amount is denominated in.")
    transactions: list[TransactionListItem] = Field(description="Matching rows, newest first.")


class SavingsSliderPayload(BaseModel):
    """Payload of a `savings_slider` widget."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "currency": "EGP",
                    "current_balance": 48200.0,
                    "default_monthly_savings": 3500.0,
                }
            ]
        }
    )

    currency: str = Field(description="ISO currency code both amounts are denominated in.")
    current_balance: float = Field(
        description="The user's most recently known balance, in `currency`."
    )
    default_monthly_savings: float = Field(
        ge=0,
        description="Starting position for the slider — observed monthly income minus "
        "recurring expense.",
    )


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


class SpendingBreakdownWidget(BaseModel):
    """Widget rendering per-category spend for one period."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "spending_breakdown",
                    "payload": {
                        "currency": "EGP",
                        "month": "July 2026",
                        "total": 3975.0,
                        "categories": [
                            {"name": "groceries", "amount": 1240.5, "pct": 31.2},
                            {"name": "housing", "amount": 2000.0, "pct": 50.3},
                            {"name": "transport", "amount": 734.5, "pct": 18.5},
                        ],
                    },
                }
            ]
        }
    )

    type: Literal["spending_breakdown"] = Field(
        default="spending_breakdown",
        description="Discriminator; always `spending_breakdown`.",
    )
    payload: SpendingBreakdownPayload = Field(description="The per-category spend breakdown.")


class TransactionsListWidget(BaseModel):
    """Widget rendering a scrollable list of the user's transactions."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "transactions_list",
                    "payload": {
                        "currency": "EGP",
                        "transactions": [
                            {
                                "id": "b3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
                                "title": "Carrefour",
                                "category": "groceries",
                                "type": "expense",
                                "amount": 340.25,
                                "date": "2026-07-14",
                            }
                        ],
                    },
                }
            ]
        }
    )

    type: Literal["transactions_list"] = Field(
        default="transactions_list",
        description="Discriminator; always `transactions_list`.",
    )
    payload: TransactionsListPayload = Field(description="The listed transactions.")


class SavingsSliderWidget(BaseModel):
    """Widget letting the user explore a savings projection. Read-only — unlike
    `allocation_slider`, adjusting it writes nothing back."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "savings_slider",
                    "payload": {
                        "currency": "EGP",
                        "current_balance": 48200.0,
                        "default_monthly_savings": 3500.0,
                    },
                }
            ]
        }
    )

    type: Literal["savings_slider"] = Field(
        default="savings_slider",
        description="Discriminator; always `savings_slider`.",
    )
    payload: SavingsSliderPayload = Field(description="The projection's starting figures.")


class InvestmentPlanAllocationPayload(BaseModel):
    instrument_id: UUID4
    instrument_code: str
    display_name: str
    asset_class: Literal["gold", "fund", "currency"]
    percentage: float = Field(ge=0, le=100)
    target_amount: float = Field(ge=0)
    unit_price: float = Field(gt=0)
    price_currency: Literal["EGP"]
    unit: str
    price_type: Literal["spot", "nav", "market_price", "customer_buy_rate"]
    minimum_increment: float = Field(gt=0)
    quantity: float = Field(ge=0)
    actual_allocated_amount: float = Field(ge=0)
    unallocated_remainder: float = Field(ge=0)
    observed_at: datetime.datetime
    source: str
    mode: Literal["live", "mock", "user_supplied"]
    priority: int | None = Field(default=None, ge=1, le=3)
    match_factors: list[
        Literal["objective", "risk", "horizon", "liquidity", "closest_available"]
    ] = Field(default_factory=list, max_length=5)


class InvestmentPlanPayload(BaseModel):
    confirmed_amount: float = Field(gt=0)
    currency: Literal["EGP"]
    allocations: list[InvestmentPlanAllocationPayload] = Field(min_length=1, max_length=3)
    total_allocated: float = Field(ge=0)
    total_remainder: float = Field(ge=0)
    disclaimer: str
    confirmed: bool = False


class InvestmentPlanWidget(BaseModel):
    """An illustrative allocation calculated from validated quote data."""

    type: Literal["investment_plan"] = Field(default="investment_plan")
    payload: InvestmentPlanPayload


# Genuinely tagged on `type` rather than a bare union: SpendingBreakdownPayload and
# TransactionsListPayload both lead with `currency` plus a list, so left-to-right
# union validation could plausibly mis-assign one to the other. Tagging makes the
# `type` field decide the branch outright, and turns a bad payload into one
# `union_tag_invalid` error instead of a confusing per-branch error list.
#
# Note this buys nothing in the OpenAPI schema: /internal/chat streams via
# StreamingResponse with no response_model, so Widget never reaches
# components.schemas at all — the SSE shape is documented by the hand-written
# frame examples in router.py. The win here is runtime validation correctness.
Widget = Annotated[
    AllocationSliderWidget
    | ProductCardWidget
    | SpendingBreakdownWidget
    | TransactionsListWidget
    | SavingsSliderWidget
    | InvestmentPlanWidget,
    Field(discriminator="type"),
]
