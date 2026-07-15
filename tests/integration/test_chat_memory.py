"""US1 Integration test: Chat memory persistence via checkpointer (Testcontainers)."""

from shutil import which

import pytest
from testcontainers.postgres import PostgresContainer


def _docker_available() -> bool:
    return which("docker") is not None


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.asyncio
async def test_chat_memory_persists_across_turns(monkeypatch):
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        monkeypatch.setenv("POSTGRES_HOST", pg.get_container_host_ip())
        monkeypatch.setenv("POSTGRES_PORT", str(pg.get_exposed_port(5432)))
        monkeypatch.setenv("POSTGRES_DB", pg.dbname)
        monkeypatch.setenv("POSTGRES_USER", pg.username)
        monkeypatch.setenv("POSTGRES_PASSWORD", pg.password)

        import importlib

        from app.core import config

        importlib.reload(config)

        from app.features.chat.checkpointer import (
            build_checkpointer,
            setup_checkpointer,
        )
        from app.features.chat.graph import build_graph

        saver = await build_checkpointer()
        await setup_checkpointer(saver)

        graph = build_graph(checkpointer=saver)

        config = {"configurable": {"thread_id": "conv-123"}}

        state1 = {
            "messages": [],
            "user_id": "7a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
            "user_context": None,
            "stage": "",
            "intent": "",
            "planner_answers": {},
            "questions_asked": 0,
            "message_references": [],
        }
        await graph.ainvoke(state1, config)

        state2 = {
            "messages": ["what did I say before?"],
            "user_context": None,
            "stage": "",
            "intent": "",
            "planner_answers": {},
            "questions_asked": 0,
            "message_references": [],
        }
        result2 = await graph.ainvoke(state2, config)

        assert "messages" in result2
        assert len(result2["messages"]) > 1

        await saver.conn.close()
