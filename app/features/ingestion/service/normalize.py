"""Part 2 — statement normalization: LLM extraction, dedup, category resolution, persistence."""

import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select

from app.backend_db.models import Category, StatementFile, StatementOcrResult
from app.core.audit import record_audit
from app.core.config import settings
from app.core.storage import get_storage_backend
from app.features.ingestion.categories import resolve_category
from app.features.ingestion.normalizer import ExtraField, find_duplicate, get_normalizer_client
from app.features.ingestion.schemas import NormalizeStatementResult


def _extra_fields_to_map(fields: list[ExtraField]) -> dict[str, str]:
    """Convert the LLM-facing `list[ExtraField]` extra facts into a `dict[str, str]`.

    The list-of-pairs shape exists solely because of the provider's strict
    structured-output constraint; this one conversion point (research.md §1,
    FR-001) keeps that constraint from leaking into the response/storage shape.
    An empty list yields an empty dict so callers can apply the "omit when
    empty" rule uniformly.
    """
    return {f.key: f.value for f in fields if f.key}


async def normalize_statement(
    session_gen,
    own_session_gen,
    ocr_result_id: str,
) -> NormalizeStatementResult:
    ocr_result = None
    statement_user_id = None
    async for session in session_gen():
        result = await session.execute(
            select(StatementOcrResult).where(StatementOcrResult.id == uuid.UUID(ocr_result_id))
        )
        ocr_result = result.scalar_one_or_none()
        if ocr_result is not None:
            user_result = await session.execute(
                select(StatementFile.user_id).where(StatementFile.id == ocr_result.statement_id)
            )
            statement_user_id = user_result.scalar_one_or_none()
        break

    if ocr_result is None:
        raise HTTPException(status_code=404, detail="ocr result not found")

    statement_id = str(ocr_result.statement_id)
    bucket = settings.storage.s3_ocr_bucket
    prefix = f"{statement_id}/"

    try:
        async with get_storage_backend() as s3:
            md_obj = await s3.get_object(Bucket=bucket, Key=f"{prefix}markdown.md")
            async with md_obj["Body"] as stream:
                markdown = (await stream.read()).decode("utf-8")
            cl_obj = await s3.get_object(Bucket=bucket, Key=f"{prefix}content_list.json")
            async with cl_obj["Body"] as stream:
                content_list_bytes = await stream.read()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"failed to retrieve OCR content: {exc}"
        ) from exc

    try:
        content_list = json.loads(content_list_bytes) if content_list_bytes else []
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"failed to parse OCR content: {exc}") from exc

    known_categories: list[str] = []
    async for backend_session in session_gen():
        known_categories = list(
            (await backend_session.execute(select(Category.name))).scalars().all()
        )
        break

    try:
        parsed, model_used = await get_normalizer_client().normalize(
            content_list,
            markdown,
            known_categories=known_categories,
            statement_id=statement_id,
            ocr_result_id=ocr_result_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"normalization engine failed: {exc}") from exc

    transactions: list[dict] = []
    async for backend_session in session_gen():
        for txn in parsed.transactions:
            raw_date = txn.transaction_date
            raw_amount = txn.amount
            try:
                txn_date = date.fromisoformat(raw_date)
                txn_amount = Decimal(str(raw_amount))
            except (TypeError, ValueError, InvalidOperation):
                # Per data-model.md: an entry without a confidently-determined
                # date/amount is omitted entirely rather than guessed at.
                continue

            category = await resolve_category(backend_session, txn.category, txn.transaction_type)
            duplicate_of = None
            if statement_user_id is not None:
                duplicate_of = await find_duplicate(
                    backend_session, statement_user_id, txn_date, txn_amount
                )
            txn_entry = {
                "transaction_date": raw_date,
                "merchant_raw": txn.merchant_raw,
                "ai_description": txn.ai_description,
                "category": category,
                "amount": raw_amount,
                "transaction_type": txn.transaction_type,
                # FR-003: dedicated, always-present keys — null when the source
                # didn't determine one (not conditionally omitted, unlike
                # extra_fields below).
                "balance": txn.balance,
                "merchant_normalized": txn.merchant_normalized,
                "duplicate_of": duplicate_of,
            }
            # FR-001: extra_fields is a key-value map at the boundary, present
            # only when non-empty. The LLM-facing contract is still a
            # list[{key, value}] (strict structured-output mode); converted to
            # a dict exactly once at this response/storage boundary.
            extra = _extra_fields_to_map(txn.extra_fields)
            if extra:
                txn_entry["extra_fields"] = extra
            transactions.append(txn_entry)
        break

    normalized_json = {
        "bank_name": parsed.bank_name,
        "account_number": parsed.account_number,
        "transactions": transactions,
    }
    statement_extra = _extra_fields_to_map(parsed.extra_fields)
    if statement_extra:
        normalized_json["extra_fields"] = statement_extra

    async with get_storage_backend() as s3:
        await s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}normalized.json",
            Body=json.dumps(normalized_json).encode("utf-8"),
        )

    full_prefix = f"{bucket}/{prefix}"
    async for own_session in own_session_gen():
        await record_audit(
            own_session,
            user_id=None,
            action="ingestion.normalize",
            detail={
                "statement_id": statement_id,
                "ocr_result_id": ocr_result_id,
                "prefix": full_prefix,
            },
        )
        await own_session.commit()
        break

    return NormalizeStatementResult(normalized_json=normalized_json, model_used=model_used)
