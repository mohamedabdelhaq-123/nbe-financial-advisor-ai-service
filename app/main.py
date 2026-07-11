"""Application assembly.

`create_app()` wires cross-cutting infrastructure to the feature slices. Each
slice owns its own router/schemas/service; this module only mounts them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import system
from app.features.analytics import router as analytics
from app.features.chat import router as chat
from app.features.plan import router as plan
from app.features.recommendations import router as recommendations


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        from app.features.chat.checkpointer import build_checkpointer, setup_checkpointer

        saver = await build_checkpointer()
        await setup_checkpointer(saver)
        app.state.checkpointer = saver
    except Exception:
        app.state.checkpointer = None
    yield
    if hasattr(app.state, "checkpointer") and app.state.checkpointer is not None:
        saver = app.state.checkpointer
        try:
            await saver.conn.close()
        except Exception:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="NBE AI Service", lifespan=_lifespan)
    app.include_router(system.router)
    app.include_router(chat.router)
    app.include_router(analytics.router)
    app.include_router(plan.router)
    app.include_router(recommendations.router)
    return app


app = create_app()
