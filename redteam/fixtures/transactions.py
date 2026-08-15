"""Fake backend-DB transaction rows and session doubles.

Mirrors the `MagicMock`-session pattern already used in
`tests/features/chat/test_analysis_agent.py` (fake row objects exposing the
same attributes `analysis_node` touches: `.id`, `.amount`, `.merchant_raw`,
`.category.name`) rather than standing up a real database — the scoping
property under test ("does the query only ever return the requesting
user's rows") is a property of `analysis_node`'s own `select(...).where(...)`
call, which these doubles let us drive without Postgres.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from redteam.fixtures.identities import USER_A_ID, USER_A_MARKER, USER_B_ID, USER_B_MARKER


@dataclass
class FakeTransaction:
    id: str
    user_id: UUID
    amount: str
    merchant_raw: str
    category_name: str = "food"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def category(self) -> SimpleNamespace | None:
        return SimpleNamespace(name=self.category_name) if self.category_name else None


def user_a_transactions() -> list[FakeTransaction]:
    return [
        FakeTransaction(
            id="11111111-0000-4000-8000-0000000000a1",
            user_id=USER_A_ID,
            amount="120.00",
            merchant_raw=USER_A_MARKER,
        ),
        FakeTransaction(
            id="11111111-0000-4000-8000-0000000000a2",
            user_id=USER_A_ID,
            amount="45.50",
            merchant_raw="Coffee Shop",
        ),
    ]


def user_b_transactions() -> list[FakeTransaction]:
    return [
        FakeTransaction(
            id="22222222-0000-4000-8000-0000000000b1",
            user_id=USER_B_ID,
            amount="980.00",
            merchant_raw=USER_B_MARKER,
        ),
    ]


class RecordingSession:
    """Fake `AsyncSession` that records every `select(...)` it's asked to
    execute and returns whichever fixed row set the scenario configured for
    it — the same shape `analysis_node` expects back from
    `session.execute(...).scalars().all()`."""

    def __init__(self, rows: list[FakeTransaction]) -> None:
        self.rows = rows
        self.executed_statements: list[Any] = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.close = AsyncMock()

    async def _execute(self, statement: Any) -> MagicMock:
        self.executed_statements.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = self.rows
        return result


def backend_session_gen_for(rows: list[FakeTransaction]):
    """Build an async-generator matching `get_backend_session`'s shape,
    backed by a `RecordingSession` seeded with `rows`. The session instance
    is returned alongside so a test can inspect `executed_statements` after
    the call (structural WHERE-clause assertions), not just the rows."""
    session = RecordingSession(rows)

    async def _gen():
        yield session

    return _gen, session


def cm_backend_session_gen_for(rows: list[FakeTransaction]):
    """Same as `backend_session_gen_for`, but shaped as a callable returning
    an async context manager (`async with session_gen() as session`) — the
    shape `compute_monthly_summary`/`detect_anomalies` expect, matching the
    `asynccontextmanager(get_backend_session)` adaptation already used at
    those routers' real call sites."""
    session = RecordingSession(rows)

    @asynccontextmanager
    async def _gen():
        yield session

    return _gen, session


# Fixed catalogue used by tests that seed "the whole backend table" once and
# then call `analysis_node` once per user — a query that (correctly) filters
# by `user_id` returns a subset; one that doesn't returns everything.
ALL_TRANSACTIONS = user_a_transactions() + user_b_transactions()
