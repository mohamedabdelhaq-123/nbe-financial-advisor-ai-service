"""Application assembly.

`create_app()` wires cross-cutting infrastructure to the feature slices. Each
slice owns its own router/schemas/service; this module only mounts them.
"""

from fastapi import FastAPI

from app.core import system
from app.features.chat import router as chat


def create_app() -> FastAPI:
    app = FastAPI(title="NBE AI Service")
    app.include_router(system.router)
    app.include_router(chat.router)
    return app


app = create_app()
