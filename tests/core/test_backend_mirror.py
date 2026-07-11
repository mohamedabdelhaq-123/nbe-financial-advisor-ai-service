"""
Offline guards for the generated backend mirror (Constitution Principle IV).

These run with no live database and no Docker: they only import the committed
`app.backend_db._generated_models` mirror and assert the ownership boundary
holds. They stay green whether or not concrete models have been generated yet,
and get stronger as tables are added.
"""

import inspect
from pathlib import Path

# Import the whole app so every OwnBase-bound feature model is registered before
# we compare metadata — the disjointness check must see the full own-DB schema.
import app.main  # noqa: F401  (import side-effect: registers feature models)
from app.backend_db import BackendBase
from app.backend_db import _generated_models as backend_models
from app.core.db import OwnBase

MODELS_FILE = Path(backend_models.__file__)
GENERATED_MARKER = "GENERATED FILE — DO NOT EDIT BY HAND."


def _backend_model_classes() -> list[type]:
    """ORM classes declared in the generated module (those with a table name)."""
    return [
        obj
        for _, obj in inspect.getmembers(backend_models, inspect.isclass)
        if hasattr(obj, "__tablename__") and obj.__module__ == backend_models.__name__
    ]


def test_generated_marker_present() -> None:
    """The committed module must announce it is generated, not hand-written."""
    assert GENERATED_MARKER in MODELS_FILE.read_text()


def test_bases_are_distinct() -> None:
    """Own and backend live behind separate registries — the whole boundary."""
    assert OwnBase is not BackendBase
    assert OwnBase.metadata is not BackendBase.metadata


def test_every_backend_model_binds_to_backend_base() -> None:
    """A model accidentally bound to OwnBase would land in the Alembic target."""
    for cls in _backend_model_classes():
        assert issubclass(cls, BackendBase), f"{cls.__name__} is not a BackendBase model"
        assert not issubclass(cls, OwnBase), f"{cls.__name__} leaks into the own-DB metadata"


def test_metadata_disjoint() -> None:
    """No backend table may appear in the own-DB metadata (Alembic's sole target).

    This is the programmatic proof that `alembic autogenerate` can never create,
    alter, or drop a backend-owned table: those tables simply are not in
    `OwnBase.metadata`, which is what migrations/env.py targets.
    """
    own = set(OwnBase.metadata.tables)
    backend = set(BackendBase.metadata.tables)
    assert own.isdisjoint(backend), f"tables in both registries: {own & backend}"
