"""Conversation ownership checks at the backend/checkpoint boundary."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.chat.service import _conversation_belongs_to_user

REQUEST_USER_ID = uuid.UUID("7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d")
CONVERSATION_ID = "3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f"


@pytest.mark.parametrize(
    ("owner_id", "expected"),
    [
        (REQUEST_USER_ID, True),
        (uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a"), False),
        (None, False),
    ],
)
async def test_conversation_owner_must_match_request_user(monkeypatch, owner_id, expected):
    result = MagicMock()
    result.scalar_one_or_none.return_value = owner_id
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    async def _backend_session():
        yield session

    monkeypatch.setattr("app.backend_db.get_backend_session", _backend_session)

    assert await _conversation_belongs_to_user(CONVERSATION_ID, REQUEST_USER_ID) is expected
    session.execute.assert_awaited_once()


async def test_invalid_conversation_id_fails_closed(monkeypatch):
    async def _unexpected_backend_session():
        raise AssertionError("invalid IDs must not reach the database")
        yield

    monkeypatch.setattr("app.backend_db.get_backend_session", _unexpected_backend_session)

    assert not await _conversation_belongs_to_user("not-a-uuid", REQUEST_USER_ID)


async def test_backend_error_fails_closed(monkeypatch):
    async def _failing_backend_session():
        raise RuntimeError("backend unavailable")
        yield

    monkeypatch.setattr("app.backend_db.get_backend_session", _failing_backend_session)

    assert not await _conversation_belongs_to_user(CONVERSATION_ID, REQUEST_USER_ID)
