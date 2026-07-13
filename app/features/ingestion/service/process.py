"""Part 1 — document processing: resolve a statement, run MinerU, persist artifacts."""

import json
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.backend_db.models import StatementFile
from app.core.audit import record_audit
from app.core.config import settings
from app.core.storage import get_storage_backend
from app.features.ingestion.mineru_client import get_mineru_client
from app.features.ingestion.schemas import ProcessStatementResult


async def process_statement(
    session_gen,
    own_session_gen,
    statement_id: str,
) -> ProcessStatementResult:
    statement = None
    async for session in session_gen():
        result = await session.execute(
            select(StatementFile).where(StatementFile.id == uuid.UUID(statement_id))
        )
        statement = result.scalar_one_or_none()
        break

    if statement is None:
        raise HTTPException(status_code=404, detail="statement not found")

    seaweed_file_id = statement.seaweed_file_id
    if not seaweed_file_id or "/" not in seaweed_file_id:
        raise HTTPException(
            status_code=502,
            detail=(
                "failed to retrieve source document: malformed seaweed_file_id "
                f"{seaweed_file_id!r}"
            ),
        )
    source_bucket, source_key = seaweed_file_id.split("/", 1)

    try:
        async with get_storage_backend() as s3:
            obj = await s3.get_object(Bucket=source_bucket, Key=source_key)
            async with obj["Body"] as stream:
                raw_bytes = await stream.read()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"failed to retrieve source document: {exc}"
        ) from exc

    filename = source_key.rsplit("/", 1)[-1]
    try:
        parsed = await get_mineru_client().parse_document(raw_bytes, filename)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"document processing engine failed: {exc}"
        ) from exc

    bucket = settings.storage_s3_ocr_bucket
    prefix = f"{statement_id}/"

    async with get_storage_backend() as s3:
        await s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}markdown.md",
            Body=parsed.markdown.encode("utf-8"),
        )
        await s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}content_list.json",
            Body=json.dumps(parsed.content_list).encode("utf-8"),
        )
        for name, image_bytes in parsed.images.items():
            await s3.put_object(
                Bucket=bucket,
                Key=f"{prefix}images/{name}",
                Body=image_bytes,
            )

    full_prefix = f"{bucket}/{prefix}"

    async for own_session in own_session_gen():
        await record_audit(
            own_session,
            user_id=None,
            action="ingestion.process",
            detail={"statement_id": statement_id, "prefix": full_prefix},
        )
        # record_audit() only flushes; this call site needs the row to be
        # durably persisted (verified by test_audit_row_persisted_in_real_own_db),
        # so commit explicitly rather than relying on the caller's session
        # scope to do it.
        await own_session.commit()
        break

    return ProcessStatementResult(prefix=full_prefix, ocr_engine="MinerU")
