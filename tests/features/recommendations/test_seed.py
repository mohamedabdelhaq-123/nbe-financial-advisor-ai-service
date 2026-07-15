"""US4 Unit test: Seed utility."""

import pytest

from app.features.recommendations.seed import seed


@pytest.mark.asyncio
async def test_seed_returns_insert_count():
    statements = [
        {
            "product_id": "5a2c1d8e-3f4b-4a2c-9e8f-2a7b6c5d4e3f",
            "statement_text": "Need a savings account",
        },
        {
            "product_id": "9f4b2a1c-2d3e-4f5a-8b7c-1d2e3f4a5b6c",
            "statement_text": "Want to invest",
        },
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
