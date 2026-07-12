"""LangGraph checkpointer infrastructure.

Checkpointer tables live in the OWN DB and are set up at startup via
`saver.setup()` which creates `checkpoints`, `checkpoint_blobs`, and
`checkpoint_writes` tables.
"""

from urllib.parse import quote

from app.core.config import settings


def _psycopg_conn_string() -> str:
    user = quote(str(settings.postgres_user), safe="")
    password = quote(str(settings.postgres_password), safe="")
    return (
        f"postgresql://{user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


async def build_checkpointer():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=_psycopg_conn_string(),
        min_size=2,
        max_size=5,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    saver = AsyncPostgresSaver(conn=pool)  # type: ignore
    return saver


async def setup_checkpointer(saver) -> None:
    try:
        await saver.setup()
    except Exception:
        await saver.conn.close()
        raise
