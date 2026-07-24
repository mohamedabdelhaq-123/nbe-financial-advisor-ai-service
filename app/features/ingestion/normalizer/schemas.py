"""Extraction schemas — the model's structured-output contract for one chunk."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator


class ExtraField(BaseModel):
    """One statement/transaction-level fact the minimum schema doesn't name.

    A list of key/value pairs rather than an open `dict` — Groq/OpenAI strict
    structured-output mode rejects an unconstrained object (`additionalProperties`
    must be `false` on every object), so this is the strict-mode-compatible
    shape for "capture whatever else appears in the document".
    """

    key: str
    value: str


class ExtractedTransaction(BaseModel):
    transaction_date: str = Field(description="ISO YYYY-MM-DD, converted from any source format")
    merchant_raw: str
    ai_description: str = Field(
        description=(
            "A concise, natural-language description of this transaction"
        )
    )
    category: str
    amount: float = Field(description="Always a positive magnitude")
    transaction_type: Literal["debit", "credit", "fee", "transfer"]
    balance: float | None = Field(
        default=None,
        description=(
            "Running balance after this transaction, when the source states one "
            "for this row. null/omit when not confidently determinable — never guess."
        ),
    )
    merchant_normalized: str | None = Field(
        default=None,
        description=(
            "Canonicalized merchant name, distinct from merchant_raw (e.g. "
            "'Carrefour' vs. a raw POS reference string). null/omit when not "
            "determinable — never guess."
        ),
    )
    extra_fields: list[ExtraField] = Field(
        default_factory=list,
        description=(
            "Any other per-transaction data visible in the source that isn't captured "
            "above (e.g. reference number, value date, running balance). Empty if none."
        ),
    )

    @field_validator("amount")
    @classmethod
    def _positive_magnitude(cls, v: float) -> float:
        # Confirmed against a real statement: the model otherwise echoes
        # whatever sign the source table happens to encode (debits as
        # negative); the contract is amount-as-magnitude, direction via
        # transaction_type. Enforced here rather than by prompt wording alone.
        return abs(v)


class ExtractedStatement(BaseModel):
    bank_name: str | None = None
    account_number: str | None = Field(
        default=None,
        description=(
            "The account number exactly as printed in the source — never masked, "
            "truncated, or redacted (FR-002). null when not determinable."
        ),
    )
    transactions: list[ExtractedTransaction] = Field(default_factory=list)
    extra_fields: list[ExtraField] = Field(
        default_factory=list,
        description=(
            "Any other statement-level data visible in the source that isn't captured "
            "above (e.g. opening/closing balance, statement period, currency, customer "
            "name). Empty if none."
        ),
    )


class NormalizerClient(Protocol):
    async def normalize(
        self,
        content_list: list,
        markdown: str,
        known_categories: list[str],
        *,
        statement_id: str,
        ocr_result_id: str,
    ) -> tuple[ExtractedStatement, str]: ...
