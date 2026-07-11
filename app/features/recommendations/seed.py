"""Admin CLI — seed problem statements into own DB.

Usage:
    uv run python -m app.features.recommendations.seed <path.json>

JSON format (list of objects):
    [
        {"product_id": 1, "statement_text": "..."},
        ...
    ]
"""

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.features.recommendations.models import AiProblemStatement


async def seed(statements: list[dict]) -> int:
    from app.features.embed.service import embed_texts

    texts = [s["statement_text"] for s in statements]
    vectors = await embed_texts(texts)

    url = settings.own_database_url
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        count = 0
        for stmt_data, vec in zip(statements, vectors):
            row = AiProblemStatement(
                product_id=stmt_data["product_id"],
                statement_text=stmt_data["statement_text"],
                embedding=vec,
            )
            session.add(row)
            count += 1
        await session.commit()

    await engine.dispose()
    return count


async def _main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.features.recommendations.seed <path.json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    data = json.loads(path.read_text())
    count = await seed(data)
    print(f"Seeded {count} problem statements")


if __name__ == "__main__":
    asyncio.run(_main())
