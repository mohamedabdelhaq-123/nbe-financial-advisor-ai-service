from __future__ import annotations

import uuid

from langchain_core.tools import BaseTool, tool

from app.core.config import settings
from app.features.market_data.repository import list_curated_instruments
from app.features.market_data.service import fetch_quotes


def make_market_price_tools() -> list[BaseTool]:
    """Return no tools when pricing is disabled; the model cannot bypass the flag."""

    if not settings.market_data.enabled:
        return []

    @tool
    async def get_market_quotes(instrument_ids: list[str]) -> dict:
        """Get latest validated prices for up to three curated investment IDs.

        Only use IDs supplied by the curated investment catalogue. This tool
        never accepts a URL, provider symbol, user data, or arbitrary ticker.
        """

        if not instrument_ids:
            return {"status": "invalid", "error": "At least one instrument is required."}
        if len(instrument_ids) > settings.market_data.max_batch_size:
            return {
                "status": "invalid",
                "error": f"At most {settings.market_data.max_batch_size} instruments are allowed.",
            }
        try:
            parsed = [uuid.UUID(item) for item in instrument_ids]
        except ValueError:
            return {"status": "invalid", "error": "Instrument IDs must be UUIDs."}
        if len(set(parsed)) != len(parsed):
            return {"status": "invalid", "error": "Instrument IDs must be unique."}

        instruments = await list_curated_instruments(parsed)
        if len(instruments) != len(parsed):
            return {"status": "invalid", "error": "One or more instruments are unavailable."}
        result = await fetch_quotes(instruments)
        return {
            "status": "ok" if not result.unavailable else "partial",
            "quotes": [quote.model_dump(mode="json") for quote in result.quotes],
            "unavailable": [str(item) for item in result.unavailable],
        }

    return [get_market_quotes]
