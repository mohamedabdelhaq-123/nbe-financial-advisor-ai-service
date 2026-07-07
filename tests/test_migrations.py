"""
Integration test: alembic upgrade head runs cleanly against a real Postgres.

Requires POSTGRES_* environment variables pointing at a live database.
Skipped automatically when they're absent (e.g. pure unit-test runs).

In CI this test runs as part of the deploy stack verification, not the
standard pytest suite (which is offline/mock-only).
For local smoke-testing with the deploy stack running:

    POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
    POSTGRES_DB=appdb POSTGRES_USER=appuser POSTGRES_PASSWORD=apppass \
    pytest tests/test_migrations.py -v
"""

import os
import subprocess
import sys

import pytest

_REQUIRED = ["POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
_DB_AVAILABLE = all(os.environ.get(v) for v in _REQUIRED)


@pytest.mark.skipif(not _DB_AVAILABLE, reason="Postgres env vars not set — skipping migration test")
def test_alembic_upgrade_head_is_noop():
    """
    alembic upgrade head must exit 0 on a fresh or already-migrated database.
    With the empty baseline migration this is always a no-op, but the command
    must complete successfully — proving the migration pipeline is wired correctly.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    assert (
        result.returncode == 0
    ), f"alembic upgrade head failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
