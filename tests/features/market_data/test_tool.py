import uuid

import pytest

from app.core.config import settings
from app.tools import market_prices as tool_module


def test_market_quote_tool_is_absent_when_feature_is_disabled(monkeypatch):
    monkeypatch.setattr(settings.market_data, "enabled", False)

    assert tool_module.make_market_price_tools() == []


@pytest.mark.asyncio
async def test_market_quote_tool_enforces_batch_and_unique_ids_before_repository_call(
    monkeypatch,
):
    monkeypatch.setattr(settings.market_data, "enabled", True)
    monkeypatch.setattr(settings.market_data, "max_batch_size", 3)

    async def unexpected_repository_call(*args, **kwargs):
        raise AssertionError("invalid requests must not query the catalogue")

    monkeypatch.setattr(tool_module, "list_curated_instruments", unexpected_repository_call)
    quote_tool = tool_module.make_market_price_tools()[0]
    repeated = str(uuid.uuid4())

    duplicate = await quote_tool.ainvoke({"instrument_ids": [repeated, repeated]})
    oversized = await quote_tool.ainvoke({"instrument_ids": [str(uuid.uuid4()) for _ in range(4)]})

    assert duplicate["status"] == "invalid"
    assert duplicate["error"] == "Instrument IDs must be unique."
    assert oversized["status"] == "invalid"
    assert oversized["error"] == "At most 3 instruments are allowed."


@pytest.mark.asyncio
async def test_market_quote_tool_rejects_non_curated_ids_without_fetching_quotes(monkeypatch):
    monkeypatch.setattr(settings.market_data, "enabled", True)
    selected_id = uuid.uuid4()

    async def no_curated_match(instrument_ids):
        assert instrument_ids == [selected_id]
        return []

    async def unexpected_quote_call(*args, **kwargs):
        raise AssertionError("unapproved instruments must not reach the provider")

    monkeypatch.setattr(tool_module, "list_curated_instruments", no_curated_match)
    monkeypatch.setattr(tool_module, "fetch_quotes", unexpected_quote_call)
    quote_tool = tool_module.make_market_price_tools()[0]

    result = await quote_tool.ainvoke({"instrument_ids": [str(selected_id)]})

    assert result == {
        "status": "invalid",
        "error": "One or more instruments are unavailable.",
    }
