"""Unit tests for the category list and resolution helper (US1/US3)."""

import pytest

from app.features.ingestion.categories import resolve_category


@pytest.mark.asyncio
async def test_resolve_category_exact_match(own_pg, seed_categories):
    async with own_pg() as session:
        assert await resolve_category(session, "groceries") == "groceries"


@pytest.mark.asyncio
async def test_resolve_category_case_insensitive_match(own_pg, seed_categories):
    async with own_pg() as session:
        assert await resolve_category(session, "Groceries") == "groceries"
        assert await resolve_category(session, "GROCERIES") == "groceries"


@pytest.mark.asyncio
async def test_resolve_category_unknown_falls_back(own_pg, seed_categories):
    async with own_pg() as session:
        assert await resolve_category(session, "spelunking-equipment") == "other"


@pytest.mark.asyncio
async def test_resolve_category_none_falls_back(own_pg, seed_categories):
    async with own_pg() as session:
        assert await resolve_category(session, None) == "other"


@pytest.mark.asyncio
async def test_resolve_category_blank_falls_back(own_pg, seed_categories):
    async with own_pg() as session:
        assert await resolve_category(session, "   ") == "other"
