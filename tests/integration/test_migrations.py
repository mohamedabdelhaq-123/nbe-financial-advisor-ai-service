"""
Integration test: `alembic upgrade head` runs cleanly against a real Postgres.

A disposable Postgres is provisioned via Testcontainers, so this always runs in
CI (where Docker is available) with no external database. Skipped locally when
Docker is not reachable.
"""

import os
import subprocess
import sys

import pytest

testcontainers = pytest.importorskip("testcontainers.postgres")
from testcontainers.postgres import PostgresContainer  # noqa: E402


def _docker_available() -> bool:
    from shutil import which

    return which("docker") is not None


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_alembic_upgrade_head_against_real_postgres():
    """`alembic upgrade head` must exit 0 against a fresh Postgres.

    Proves the async migration pipeline is wired to the own-DB metadata.
    """
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        env = {
            **os.environ,
            "POSTGRES_HOST": pg.get_container_host_ip(),
            "POSTGRES_PORT": str(pg.get_exposed_port(5432)),
            "POSTGRES_DB": pg.dbname,
            "POSTGRES_USER": pg.username,
            "POSTGRES_PASSWORD": pg.password,
            # config fail-fast guards — irrelevant to migrations
            "USE_MOCK_LLM": "1",
            "AI_SERVICE_TOKEN": "test-token-for-ci",
        }
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
        )
        message = f"alembic upgrade head failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        assert result.returncode == 0, message

        import psycopg

        with psycopg.connect(pg.get_connection_url().replace("+psycopg2", "")) as conn:
            rows = conn.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_name IN
                    ('ai_audit_log', 'ai_problem_statements', 'ai_recommendation_logs')
                AND column_name IN ('user_id', 'product_id')
                """).fetchall()

        # SC-001: every own-DB identifier column the service owns is a native UUID
        # after a fresh provisioning of the amended migration (research.md D2).
        by_table_column = {(table, column): data_type for table, column, data_type in rows}
        assert by_table_column == {
            ("ai_audit_log", "user_id"): "uuid",
            ("ai_problem_statements", "product_id"): "uuid",
            ("ai_recommendation_logs", "user_id"): "uuid",
            ("ai_recommendation_logs", "product_id"): "uuid",
        }
