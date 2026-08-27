"""Recommendation catalogue synchronization tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.recommendations.models import AiProblemStatement
from app.features.recommendations.sync import (
    SourceProblemStatement,
    sync_problem_statements,
)


def _result_with(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_sync_embeds_and_creates_missing_backend_statements(monkeypatch):
    sources = [
        SourceProblemStatement(uuid.uuid4(), uuid.uuid4(), "Need a savings account"),
        SourceProblemStatement(uuid.uuid4(), uuid.uuid4(), "Need a salary-backed loan"),
    ]
    monkeypatch.setattr(
        "app.features.recommendations.sync._load_source_statements",
        AsyncMock(return_value=sources),
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result_with([]))
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    embedded_texts = []

    async def _embed(texts):
        embedded_texts.extend(texts)
        return [[float(index)] * 768 for index, _ in enumerate(texts, start=1)]

    result = await sync_problem_statements(session, embed_fn=_embed)

    assert result.created == 2
    assert result.updated == 0
    assert result.deleted == 0
    assert embedded_texts == [source.index_text for source in sources]
    assert session.add.call_count == 2
    assert session.commit.await_count == 1
    added = [call.args[0] for call in session.add.call_args_list]
    assert [row.source_statement_id for row in added] == [source.id for source in sources]
    assert [row.product_id for row in added] == [source.product_id for source in sources]


@pytest.mark.asyncio
async def test_sync_updates_changed_rows_and_removes_stale_rows(monkeypatch):
    source_id = uuid.uuid4()
    new_product_id = uuid.uuid4()
    source = SourceProblemStatement(source_id, new_product_id, "Updated savings need")
    stale = AiProblemStatement(
        source_statement_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        statement_text="Deleted backend statement",
        embedding=[0.1] * 768,
    )
    changed = AiProblemStatement(
        source_statement_id=source_id,
        product_id=uuid.uuid4(),
        statement_text="Old savings need",
        embedding=[0.2] * 768,
    )
    monkeypatch.setattr(
        "app.features.recommendations.sync._load_source_statements",
        AsyncMock(return_value=[source]),
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result_with([changed, stale]))
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    async def _embed(texts):
        assert texts == [source.index_text]
        return [[0.9] * 768]

    result = await sync_problem_statements(session, embed_fn=_embed)

    assert result.created == 0
    assert result.updated == 1
    assert result.deleted == 1
    assert changed.product_id == new_product_id
    assert changed.statement_text == source.index_text
    assert changed.embedding == [0.9] * 768
    session.delete.assert_awaited_once_with(stale)
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_sync_does_not_reembed_unchanged_rows(monkeypatch):
    existing = AiProblemStatement(
        source_statement_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        statement_text="Need a savings account",
        embedding=[0.5] * 768,
    )
    source = SourceProblemStatement(
        existing.source_statement_id,
        existing.product_id,
        existing.statement_text,
    )
    monkeypatch.setattr(
        "app.features.recommendations.sync._load_source_statements",
        AsyncMock(return_value=[source]),
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result_with([existing]))
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    async def _unexpected_embed(texts):
        raise AssertionError("unchanged statements must not be embedded again")

    result = await sync_problem_statements(session, embed_fn=_unexpected_embed)

    assert result.created == 0
    assert result.updated == 0
    assert result.deleted == 0
    session.add.assert_not_called()
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_rejects_incomplete_embedding_batches(monkeypatch):
    source = SourceProblemStatement(uuid.uuid4(), uuid.uuid4(), "Need savings")
    monkeypatch.setattr(
        "app.features.recommendations.sync._load_source_statements",
        AsyncMock(return_value=[source]),
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result_with([]))

    async def _incomplete_embed(texts):
        return []

    with pytest.raises(RuntimeError, match="incomplete recommendation batch"):
        await sync_problem_statements(session, embed_fn=_incomplete_embed)

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_sync_uses_cached_index_when_backend_catalogue_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.features.recommendations.sync._load_source_statements",
        AsyncMock(side_effect=ConnectionError("backend unavailable")),
    )
    session = MagicMock()
    session.execute = AsyncMock()

    result = await sync_problem_statements(session, embed_fn=AsyncMock())

    assert result.created == 0
    assert result.updated == 0
    assert result.deleted == 0
    session.execute.assert_not_awaited()
