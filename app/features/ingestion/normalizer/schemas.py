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
            "A verbose, natural-language description of this transaction — several "
            "sentences, not a restatement of merchant_raw. Cover what the transaction "
            "likely was for, the merchant/counterparty, and any other relevant context "
            "visible in this fragment (e.g. location, reference details, recurring-payment "
            "signals)."
        )
    )
    category: str
    amount: float = Field(description="Always a positive magnitude")
    transaction_type: Literal["debit", "credit", "fee", "transfer"]
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
    account_hint: str | None = None
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
        self, content_list: list, markdown: str, known_categories: list[str]
    ) -> tuple[dict, str]: ...
