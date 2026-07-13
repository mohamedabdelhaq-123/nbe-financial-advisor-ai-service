"""Request/response contracts for the ingestion slice."""

from uuid import UUID

from pydantic import BaseModel


class ProcessStatementRequest(BaseModel):
    statement_id: UUID


class ProcessStatementResult(BaseModel):
    prefix: str
    ocr_engine: str


class NormalizeStatementRequest(BaseModel):
    ocr_result_id: UUID


class NormalizeStatementResult(BaseModel):
    normalized_json: dict
    model_used: str
