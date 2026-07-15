"""Recommendation service — RAG match over problem statements."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.recommendations.models import (
    AiProblemStatement,
    AiRecommendationLog,
)
from app.features.recommendations.schemas import ProductMatch

SIMILARITY_THRESHOLD = 0.5

_PRODUCT_TITLE_FALLBACK = "Product unavailable"


async def _fetch_product_titles(product_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Read-only lookup of real product titles from the backend `Products` table.

    Degrades gracefully on backend outage (matches analysis.py's pattern) — a
    transient backend DB failure must not crash the chat turn or the match call.
    """
    try:
        from app.backend_db import get_backend_session
        from app.backend_db.models import Product

        async for session in get_backend_session():
            result = await session.execute(
                select(Product.id, Product.title).where(Product.id.in_(product_ids))
            )
            return {product_id: title for product_id, title in result.all()}
    except Exception:
        return {}
    return {}


async def match(
    session: AsyncSession,
    embed_fn=None,
    user_id: uuid.UUID | None = None,
    query: str = "",
    top_k: int = 5,
) -> list[ProductMatch]:
    if embed_fn is None:
        from app.features.embed.service import embed_texts

        embed_fn = embed_texts

    if not query.strip():
        return []

    vectors = await embed_fn([query])
    query_vec = vectors[0] if vectors else []

    if not query_vec:
        return []

    similarity = 1 - AiProblemStatement.embedding.cosine_distance(query_vec)

    stmt = (
        select(
            AiProblemStatement.product_id,
            AiProblemStatement.statement_text,
            similarity.label("score"),
        )
        .where(AiProblemStatement.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    kept_rows = [row for row in rows if row.score >= SIMILARITY_THRESHOLD]
    titles = await _fetch_product_titles([row.product_id for row in kept_rows])

    matches: list[ProductMatch] = []
    for product_id, statement_text, score in kept_rows:
        matches.append(
            ProductMatch(
                product_id=product_id,
                product_name=titles.get(product_id, _PRODUCT_TITLE_FALLBACK),
                similarity=round(float(score), 4),
            )
        )

        log = AiRecommendationLog(
            user_id=user_id,
            product_id=product_id,
            matched_query=query,
            similarity_score=float(score),
            shown_at=datetime.now(timezone.utc),
        )
        session.add(log)

    if matches:
        await session.flush()
        await session.commit()
    return matches
