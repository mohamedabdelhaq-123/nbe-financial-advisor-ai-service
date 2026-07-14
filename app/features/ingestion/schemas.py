"""Request/response contracts for the ingestion slice."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProcessStatementRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"statement_id": "b3f1c2d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"}]}
    )

    statement_id: UUID = Field(
        description="Backend statement ID of a previously uploaded document to extract."
    )


class ProcessStatementResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "prefix": "statements/1001/b3f1c2d4/",
                    "ocr_engine": "mineru",
                    "confidence_score": 1.0,
                }
            ]
        }
    )

    prefix: str = Field(
        description="Object-storage key prefix under which the extracted artifacts were saved."
    )
    ocr_engine: str = Field(description="Identifier of the OCR engine that performed extraction.")
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Extraction confidence in [0.0, 1.0]; always 1.0 on success.",
    )


class NormalizeStatementRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"ocr_result_id": "c4d5e6f7-8a9b-0c1d-2e3f-4a5b6c7d8e9f"}]}
    )

    ocr_result_id: UUID = Field(
        description="ID of a previously processed statement's OCR result to normalize."
    )


class NormalizeStatementResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "normalized_json": {
                        "transactions": [
                            {"date": "2026-06-03", "amount": -45.20, "description": "Groceries"}
                        ]
                    },
                    "model_used": "gpt-4o-mini",
                }
            ]
        }
    )

    normalized_json: dict = Field(
        description="Structured transactions extracted from the statement's OCR content."
    )
    model_used: str = Field(description="Identifier of the LLM that performed normalization.")
