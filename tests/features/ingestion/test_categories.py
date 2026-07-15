"""Unit tests for the category resolution helper (US1/US3).

The category taxonomy is backend-owned now (see tests/conftest.py's
`own_db_url` fixture, which seeds the same mock `categories` table the real
backend migration seeds) — resolve_category() reads it through a backend
session, not its own table.
"""

import pytest

from app.features.ingestion.categories import resolve_category


@pytest.mark.asyncio
async def test_resolve_category_exact_match(own_pg):
    async with own_pg() as session:
        assert await resolve_category(session, "food") == "food"


@pytest.mark.asyncio
async def test_resolve_category_case_insensitive_match(own_pg):
    async with own_pg() as session:
        assert await resolve_category(session, "Food") == "food"
        assert await resolve_category(session, "FOOD") == "food"


@pytest.mark.asyncio
async def test_resolve_category_unknown_falls_back_to_expense_fallback(own_pg):
    async with own_pg() as session:
        assert await resolve_category(session, "spelunking-equipment", "debit") == "other"


@pytest.mark.asyncio
async def test_resolve_category_unknown_credit_falls_back_to_income_fallback(own_pg):
    async with own_pg() as session:
        assert await resolve_category(session, "spelunking-equipment", "credit") == "other_income"


@pytest.mark.asyncio
async def test_resolve_category_none_falls_back(own_pg):
    async with own_pg() as session:
        assert await resolve_category(session, None, "debit") == "other"


@pytest.mark.asyncio
async def test_resolve_category_blank_falls_back(own_pg):
    async with own_pg() as session:
        assert await resolve_category(session, "   ", "debit") == "other"


@pytest.mark.asyncio
async def test_resolve_category_defaults_to_expense_fallback_when_type_omitted(own_pg):
    async with own_pg() as session:
        assert await resolve_category(session, None) == "other"
