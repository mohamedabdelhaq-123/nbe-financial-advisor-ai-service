"""Application assembly.

`create_app()` wires cross-cutting infrastructure to the feature slices. Each
slice owns its own router/schemas/service; this module only mounts them.
"""

import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from fastapi import FastAPI

from app.core import logging as app_logging
from app.core import observability as app_observability
from app.core import system
from app.core.logging import get_logger
from app.core.request_logging import RequestLoggingMiddleware
from app.core.tasks import router as tasks
from app.features.analytics import router as analytics
from app.features.chat import router as chat
from app.features.embed import router as embed
from app.features.ingestion import router as ingestion
from app.features.plan import router as plan
from app.features.recommendations import router as recommendations
from app.features.transactions import router as transactions

app_logging.configure()
app_observability.configure()

logger = get_logger(__name__)


def _resolve_version() -> str:
    """Source of truth is ``pyproject.toml``; fall back to installed dist metadata."""
    try:
        return _pkg_version("nbe-ai-service")
    except PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as fh:
            return tomllib.load(fh).get("project", {}).get("version", "0.0.0+local")
    return "0.0.0+local"


VERSION = _resolve_version()

_OPENAPI_TAGS = [
    {
        "name": "chat",
        "description": (
            "Internal SSE streaming endpoint for the Maestro conversation orchestrator. "
            "Streams the assistant's reply over the shared `{event, data}` envelope and "
            "concludes with one terminal `done` event. See "
            "specs/009-chat-streaming-contract/contracts/chat-stream.md."
        ),
    },
    {"name": "system", "description": "Liveness and readiness probes (no auth)."},
    {
        "name": "tasks",
        "description": (
            "Generic status read for any feature's asynchronous job, by the reference its "
            "own submission endpoint returned. Submission itself is feature-owned — see "
            "e.g. the ingestion tag's `/jobs/*` routes."
        ),
    },
]

_DESCRIPTION = (
    "NBE AI-PFM service. Internal FastAPI AI service invoked solely by the Django "
    "backend; exposes the Maestro orchestrator, analytics, plan, recommendations, "
    "embed, ingestion, and transactions slices behind a shared-secret Bearer token."
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio

    from app.core.tasks.queue import build_queue, set_queue
    from app.core.tasks.worker import build_worker
    from app.features.chat.checkpointer import build_checkpointer, setup_checkpointer
    from app.features.ingestion.tasks import JOB_FUNCTIONS as INGESTION_JOB_FUNCTIONS

    try:
        saver = await build_checkpointer()
        await setup_checkpointer(saver)
    except Exception:
        logger.exception("checkpointer_setup_failed")
        raise
    app.state.checkpointer = saver

    # The job queue runs on the own DB and creates its own tables on connect. Failing
    # here aborts startup rather than serving a submission surface that silently never
    # executes anything.
    try:
        queue = build_queue()
        await queue.connect()
    except Exception:
        logger.exception("job_queue_setup_failed")
        raise
    set_queue(queue)
    # Slices contribute their job functions here, the same way they contribute routers in
    # create_app() below — an explicit list, not a discovery mechanism. A second feature
    # adding jobs later just adds its own import and appends to this list.
    worker = build_worker(queue, functions=[*INGESTION_JOB_FUNCTIONS])
    # The worker owns no signal handlers (see build_worker); this task is how it stops.
    worker_task = asyncio.create_task(worker.start())
    app.state.job_worker = worker
    app.state.job_worker_task = worker_task

    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("job_worker_shutdown_failed")
    try:
        await queue.disconnect()
    except Exception:
        logger.exception("job_queue_disconnect_failed")
    set_queue(None)

    if hasattr(app.state, "checkpointer") and app.state.checkpointer is not None:
        saver = app.state.checkpointer
        try:
            await saver.conn.close()
        except Exception:
            pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="NBE AI Service",
        version=VERSION,
        description=_DESCRIPTION,
        openapi_tags=_OPENAPI_TAGS,
        lifespan=_lifespan,
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(system.router)
    app.include_router(tasks.router)
    app.include_router(chat.router)
    app.include_router(embed.router)
    app.include_router(analytics.router)
    app.include_router(ingestion.router)
    app.include_router(plan.router)
    app.include_router(recommendations.router)
    app.include_router(transactions.router)
    return app


app = create_app()
