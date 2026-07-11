"""US4 Unit test: Seed utility."""

import pytest

from app.features.recommendations.seed import seed


@pytest.mark.asyncio
async def test_seed_returns_insert_count(mock_embedder):
    statements = [
        {"product_id": 1, "statement_text": "Need a savings account"},
        {"product_id": 2, "statement_text": "Want to invest"},
    ]

    from unittest.mock import AsyncMock, MagicMock, patch

    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    with (
        patch(
            "app.features.recommendations.seed.create_async_engine",
            return_value=mock_engine,
        ),
        patch(
            "app.features.recommendations.seed.async_sessionmaker",
            return_value=mock_factory,
        ),
    ):
        count = await seed(statements)

    assert count == 2
    assert mock_session.add.call_count == 2
