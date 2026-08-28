"""Synchronize backend product statements into the AI-owned vector index."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.features.recommendations.models import AiProblemStatement

EmbedFunction = Callable[[list[str]], Awaitable[list[list[float]]]]
logger = get_logger(__name__)


@dataclass(frozen=True)
class SourceProblemStatement:
    id: uuid.UUID
    product_id: uuid.UUID
    index_text: str


@dataclass(frozen=True)
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0


_sync_lock = asyncio.Lock()


async def _load_source_statements() -> list[SourceProblemStatement]:
    """Read active product statements through the backend read-only role."""

    from app.backend_db import get_backend_session
    from app.backend_db.models import ProblemStatement, Product

    statement = (
        select(
            ProblemStatement.id,
            ProblemStatement.product_id,
            Product.title,
            ProblemStatement.statement_text,
        )
        .join(Product, Product.id == ProblemStatement.product_id)
        .where(Product.is_active.is_(True))
        .order_by(ProblemStatement.id)
    )
    async for backend_session in get_backend_session():
        try:
            result = await backend_session.execute(statement)
            return [
                SourceProblemStatement(
                    id=statement_id,
                    product_id=product_id,
                    index_text=f"{product_title}. {statement_text}",
                )
                for statement_id, product_id, product_title, statement_text in result.all()
            ]
        finally:
            await backend_session.close()
    return []


async def sync_problem_statements(
    session: AsyncSession,
    *,
    embed_fn: EmbedFunction | None = None,
) -> SyncResult:
    """Make the local vector index mirror active backend source statements.

    The process-wide lock prevents two concurrent chat turns from embedding
    and inserting the same newly seeded rows. A database uniqueness constraint
    on ``source_statement_id`` provides the persistence-level invariant.
    """

    if embed_fn is None:
        from app.features.embed.service import embed_texts

        embed_fn = embed_texts

    async with _sync_lock:
        try:
            sources = await _load_source_statements()
        except Exception as exc:
            # The local vector index is a usable cache. A temporary backend
            # catalogue outage must not take product recommendations down with
            # it; matching can continue against the last successful sync.
            logger.warning(
                "recommendation_catalog_sync_skipped",
                error_type=type(exc).__name__,
            )
            return SyncResult()
        existing_result = await session.execute(
            select(AiProblemStatement).where(AiProblemStatement.source_statement_id.isnot(None))
        )
        existing = {
            row.source_statement_id: row
            for row in existing_result.scalars().all()
            if row.source_statement_id is not None
        }
        source_ids = {source.id for source in sources}

        stale = [row for source_id, row in existing.items() if source_id not in source_ids]
        changed = [
            source
            for source in sources
            if source.id not in existing
            or existing[source.id].product_id != source.product_id
            or existing[source.id].statement_text != source.index_text
        ]

        vectors = await embed_fn([source.index_text for source in changed]) if changed else []
        if len(vectors) != len(changed):
            raise RuntimeError("embedding provider returned an incomplete recommendation batch")

        created = 0
        updated = 0
        for source, vector in zip(changed, vectors, strict=True):
            row = existing.get(source.id)
            if row is None:
                session.add(
                    AiProblemStatement(
                        source_statement_id=source.id,
                        product_id=source.product_id,
                        statement_text=source.index_text,
                        embedding=vector,
                    )
                )
                created += 1
            else:
                row.product_id = source.product_id
                row.statement_text = source.index_text
                row.embedding = vector
                updated += 1

        for row in stale:
            await session.delete(row)

        if created or updated or stale:
            await session.commit()

        return SyncResult(created=created, updated=updated, deleted=len(stale))
