"""Reference model — a citation to an underlying financial record.

Per FR-006, ``target_type`` is constrained to ``{transaction, statement}``.
References carry only a record type and a UUID — never merchant/amount PII
(Constitution Principle III).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TargetType = Literal["transaction", "statement"]


class Reference(BaseModel):
    """A citation pointing at one underlying financial record."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "target_type": "transaction",
                    "target_id": "b3f1c2d4-0000-0000-0000-000000000000",
                }
            ]
        }
    )

    target_type: TargetType = Field(
        description="The kind of record cited; one of `transaction` or `statement`."
    )
    target_id: str = Field(
        description="UUID of the cited record. No PII (Constitution Principle III)."
    )
