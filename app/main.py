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
]

_DESCRIPTION = (
    "NBE AI-PFM service. Internal FastAPI AI service invoked solely by the Django "
    "backend; exposes the Maestro orchestrator, analytics, plan, recommendations, "
    "embed, ingestion, and transactions slices behind a shared-secret Bearer token."
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.features.chat.checkpointer import build_checkpointer, setup_checkpointer

    try:
        saver = await build_checkpointer()
        await setup_checkpointer(saver)
    except Exception:
        logger.exception("checkpointer_setup_failed")
        raise
    app.state.checkpointer = saver
    yield
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
    app.include_router(chat.router)
    app.include_router(embed.router)
    app.include_router(analytics.router)
    app.include_router(ingestion.router)
    app.include_router(plan.router)
    app.include_router(recommendations.router)
    app.include_router(transactions.router)
    return app


app = create_app()
