"""Recommendation service — RAG match over problem statements."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.recommendations.models import (
    AiProblemStatement,
    AiRecommendationLog,
)
from app.features.recommendations.schemas import ProductMatch

SIMILARITY_THRESHOLD = 0.5


async def match(
    session: AsyncSession,
    embed_fn=None,
    user_id: int = 0,
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

    matches: list[ProductMatch] = []
    for product_id, statement_text, score in rows:
        if score < SIMILARITY_THRESHOLD:
            continue

        matches.append(
            ProductMatch(
                product_id=product_id,
                product_name=f"Product {product_id}",
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

    return matches
