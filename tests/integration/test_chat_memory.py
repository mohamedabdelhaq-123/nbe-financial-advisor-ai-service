"""US1 Integration test: Chat memory persistence via checkpointer (Testcontainers)."""

import os
from shutil import which

import pytest
from testcontainers.postgres import PostgresContainer


def _docker_available() -> bool:
    return which("docker") is not None


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.asyncio
async def test_chat_memory_persists_across_turns():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        os.environ["POSTGRES_HOST"] = pg.get_container_host_ip()
        os.environ["POSTGRES_PORT"] = str(pg.get_exposed_port(5432))
        os.environ["POSTGRES_DB"] = pg.dbname
        os.environ["POSTGRES_USER"] = pg.username
        os.environ["POSTGRES_PASSWORD"] = pg.password

        import importlib

        from app.core import config

        importlib.reload(config)

        from app.core.config import settings

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
            "user_context": {"user_id": 1},
            "stage": "",
            "intent": "",
            "planner_answers": {},
            "questions_asked": 0,
            "message_references": [],
        }
        await graph.ainvoke(state1, config)

        state2 = {
            "messages": ["what did I say before?"],
            "user_context": {},
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
