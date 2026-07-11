"""LangGraph checkpointer infrastructure.

Checkpointer tables live in the OWN DB and are set up at startup via
`saver.setup()` which creates `checkpoints`, `checkpoint_blobs`, and
`checkpoint_writes` tables.
"""

from app.core.config import settings


def _psycopg_conn_string() -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


async def build_checkpointer():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=_psycopg_conn_string(),
        min_size=2,
        max_size=5,
        open=False,
    )
    await pool.open()
    saver = AsyncPostgresSaver(conn=pool)
    return saver


async def setup_checkpointer(saver) -> None:
    await saver.setup()
