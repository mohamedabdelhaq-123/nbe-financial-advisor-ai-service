"""LangGraph checkpointer infrastructure.

Checkpointer tables live in the OWN DB and are set up at startup via
`saver.setup()` which creates `checkpoints`, `checkpoint_blobs`, and
`checkpoint_writes` tables.
"""

from urllib.parse import quote

from app.core.config import settings


def _psycopg_conn_string() -> str:
    user = quote(str(settings.own_db.postgres_user), safe="")
    password = quote(settings.own_db.postgres_password.get_secret_value(), safe="")
    return (
        f"postgresql://{user}:{password}"
        f"@{settings.own_db.postgres_host}:{settings.own_db.postgres_port}"
        f"/{settings.own_db.postgres_db}"
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
        max_lifetime=1800,
        check=AsyncConnectionPool.check_connection,
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
