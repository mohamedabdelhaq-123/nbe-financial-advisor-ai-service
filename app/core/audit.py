"""Audit helper — records privileged actions per Constitution III."""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def record_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    detail: dict,
) -> None:
    from app.features.audit.models import AiAuditLog

    row = AiAuditLog(
        user_id=user_id,
        action=action,
        detail_json=json.dumps(detail, default=str),
    )
    session.add(row)
    await session.flush()
