#!/usr/bin/env python3
"""
Regenerate app/backend_db/_generated_models.py from the LIVE read-only backend database.

This is a MANUAL developer step (Constitution Principle IV): the backend-owned
tables are mirrored as generated typed models rather than hand-written ones. There
is no committed schema snapshot and no CI/scheduled automation — drift against the
backend schema is reconciled whenever a developer reruns this script and commits
the result.

Usage (the `codegen` dependency group carries the pinned generator + sync driver):

    uv run --group codegen python scripts/gen_backend_models.py \
        --tables auth_user accounts_account

Connection is read from the same BACKEND_DB_* settings the app uses — from the
repo's `.env` and/or the environment (real env vars override `.env`) — but built
as a SYNC psycopg URL (sqlacodegen reflects synchronously). The app runtime stays
asyncpg-only; psycopg lives only in the `codegen` group.

NOTE: the value must be reachable from wherever you run this. Inside the compose
network BACKEND_DB_HOST is `postgres`; from the host use a reachable host/port
(the postgres container IP, or a published port) — override on the command line
or in `.env`.

When --tables is omitted (mirror the whole schema), Django's own
framework-internal tables (auth_group, auth_permission, django_migrations,
django_content_type, django_admin_log, django_session, and their M2M join
tables) are excluded by default — pass --include-django to mirror them too.

The generated module is post-processed to bind its models to `BackendBase` (so the
Alembic exclusion keeps holding) and formatted with the repo's ruff+black so it
passes CI unchanged.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "app" / "backend_db" / "_generated_models.py"

# Django's own framework-internal tables (auth/session/migration/content-type
# bookkeeping) — not app data. These are mirrored only with --include-django;
# by default they're dropped from a full-schema (no --tables) generation.
DJANGO_INTERNAL_TABLES = {
    "django_migrations",
    "django_content_type",
    "django_admin_log",
    "django_session",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "auth_user_groups",
    "auth_user_user_permissions",
}


class _BackendDBEnv(BaseSettings):
    """The app's BACKEND_DB_* settings, read from `.env` and the environment.

    Scoped deliberately: importing `app.core.config` would trip its unrelated
    fail-fast (e.g. AI_SERVICE_TOKEN). This mirrors only the backend-DB fields so
    regeneration needs nothing but a reachable read-only backend. Real environment
    variables take precedence over `.env`, so a one-off override still works.
    """

    backend_db_host: str = ""
    backend_db_port: str = "5432"
    backend_db_name: str = ""
    backend_db_user: str = ""
    backend_db_password: str = ""
    backend_db_schema: str = ""

    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")


GENERATED_HEADER = '''"""
GENERATED FILE — DO NOT EDIT BY HAND.

Read-only mirror of backend (Django-owned) tables, generated directly from the
live read-only backend database by scripts/gen_backend_models.py (sqlacodegen).
Regenerate and commit rather than editing; see Constitution Principle IV.

These models bind to `BackendBase` (excluded from Alembic) and are never written.
"""
'''


def _fail(msg: str) -> NoReturn:
    sys.stderr.write(f"error: {msg}\n")
    raise SystemExit(1)


def _sync_backend_url(env: _BackendDBEnv) -> str:
    """Build a SYNC psycopg URL from the BACKEND_DB_* settings, or fail loudly."""
    host, name, user = (
        env.backend_db_host.strip(),
        env.backend_db_name.strip(),
        env.backend_db_user.strip(),
    )
    if not (host and name and user):
        _fail(
            "backend database is not configured. Set BACKEND_DB_HOST, "
            "BACKEND_DB_NAME and BACKEND_DB_USER (a READ-ONLY role), plus "
            "BACKEND_DB_PASSWORD/BACKEND_DB_PORT as needed, in .env or the "
            "environment before regenerating."
        )
    port = env.backend_db_port.strip() or "5432"
    auth = quote(user, safe="")
    if env.backend_db_password:
        auth += f":{quote(env.backend_db_password, safe='')}"
    return f"postgresql+psycopg://{auth}@{host}:{port}/{name}"


def _resolve_tables(
    url: str, tables: list[str] | None, schema: str | None, include_django: bool
) -> list[str] | None:
    """Work out which tables to hand sqlacodegen.

    Explicit `--tables` is honored as-is (the user asked for exactly those,
    Django-internal or not). Otherwise, for a full-schema generation, Django's
    own internal tables are excluded by default since sqlacodegen has no
    native exclude flag — this reflects the schema's table names and passes
    everything but those explicitly back in as `--tables`.
    """
    if tables or include_django:
        return tables
    inspector = inspect(create_engine(url))
    all_tables = inspector.get_table_names(schema=schema)
    return [t for t in all_tables if t not in DJANGO_INTERNAL_TABLES]


def _run_sqlacodegen(url: str, tables: list[str] | None, schema: str | None) -> str:
    """Invoke the pinned sqlacodegen and return its declarative output.

    When `tables` is empty/None, sqlacodegen mirrors ALL tables in the schema.
    """
    exe = shutil.which("sqlacodegen")
    if exe is None:
        _fail(
            "sqlacodegen not found on PATH. Run via the codegen group:\n"
            "  uv run --group codegen python scripts/gen_backend_models.py ..."
        )
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        cmd = [exe, url, "--generator", "declarative", "--outfile", str(tmp_path)]
        if tables:
            cmd += ["--tables", ",".join(tables)]
        if schema:
            cmd += ["--schemas", schema]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            _fail(f"sqlacodegen failed:\n{proc.stderr.strip()}")
        raw = tmp_path.read_text()
        if not raw.strip():
            _fail("sqlacodegen produced no output (do the requested tables exist?)")
        return raw
    finally:
        tmp_path.unlink(missing_ok=True)


def _rebind_to_backend_base(code: str) -> str:
    """Rewrite sqlacodegen's own `Base` onto the project's `BackendBase`.

    sqlacodegen emits `class Base(DeclarativeBase): pass` and subclasses it. We
    drop that local base and its `DeclarativeBase` import, import `BackendBase`
    from the package instead, and re-parent every generated model onto it. This
    keeps backend models on the Alembic-excluded Base by construction.
    """

    # Drop DeclarativeBase from the `from sqlalchemy.orm import ...` line.
    def _strip_declbase(m: re.Match[str]) -> str:
        names = [n.strip() for n in m.group(1).split(",")]
        names = [n for n in names if n and n != "DeclarativeBase"]
        return f"from sqlalchemy.orm import {', '.join(names)}" if names else ""

    code = re.sub(r"^from sqlalchemy\.orm import (.+)$", _strip_declbase, code, flags=re.MULTILINE)
    # Remove the generated `class Base(DeclarativeBase): pass` block.
    code = re.sub(r"\nclass Base\(DeclarativeBase\):\n    pass\n", "\n", code)
    # Re-parent every model onto BackendBase.
    code = code.replace("(Base):", "(BackendBase):")
    # Ensure the BackendBase import exists (ruff will sort it into place).
    import_line = "from app.backend_db import BackendBase\n"
    if import_line not in code:
        code = import_line + code
    return code


def _neutralize_unmapped_types(code: str) -> str:
    """Make columns of DB types sqlacodegen can't map importable.

    For a type with no SQLAlchemy mapping (e.g. pgvector `vector`), sqlacodegen
    emits `name: Mapped[Optional[Any]] = mapped_column(NullType)`. SQLAlchemy 2.0
    cannot configure that: `NullType` reads as "no type" so it falls back to the
    `Mapped[Any]` annotation, which is unresolvable — and dropping the annotation
    instead trips the "annotation required" guard. Both dead ends.

    Represent such columns faithfully as an opaque classic `Column(NullType())`:
    importable (classic columns need no `Mapped[]` annotation), honest that the
    type is unknown to SQLAlchemy, and never used through the ORM anyway (this is
    a read-only mirror). The column remains present so the mirror is full-table.
    """

    def _to_classic_column(m: re.Match[str]) -> str:
        return f"{m.group(1)}{m.group(2)} = Column(NullType())"

    # `.*` is line-scoped (no DOTALL) and anchored by ` = mapped_column(NullType`,
    # so it spans the whole `Mapped[...]` even when nested (`Mapped[Optional[Any]]`)
    # and the trailing `[^\n]*\)` consumes any extra mapped_column() arguments.
    new = re.sub(
        r"^(\s*)(\w+): Mapped\[.*\bAny\b.*\] = mapped_column\(NullType\b[^\n]*\)",
        _to_classic_column,
        code,
        flags=re.MULTILINE,
    )
    if new != code:
        # `Column` is not in sqlacodegen's declarative imports; add it (ruff sorts
        # and merges it into the existing `from sqlalchemy import ...`).
        new = "from sqlalchemy import Column\n" + new
    return new


def _format_in_place(path: Path) -> None:
    """Format the generated file so it passes the repo's ruff+black gates unchanged.

    Order matters: black runs FIRST so it wraps long `relationship(...)` lines
    (E501 is not ruff-auto-fixable and would otherwise abort the pass); ruff then
    sorts imports and drops any unused ones; a final black re-settles anything ruff
    rewrote. black/ruff discover line-length 100 from pyproject via the file path.
    """
    steps = (
        ["black", "--quiet", str(path)],
        ["ruff", "check", "--fix", "--quiet", str(path)],
        ["black", "--quiet", str(path)],
    )
    for cmd in steps:
        exe = shutil.which(cmd[0])
        if exe is None:
            _fail(f"{cmd[0]} not found on PATH; run inside `uv run` so dev tools resolve.")
        result = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True)
        if result.returncode != 0:
            _fail(f"{cmd[0]} failed on generated file:\n{result.stderr.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tables",
        nargs="*",
        default=None,
        help=(
            "Backend tables to mirror (FK-referenced tables are pulled in "
            "automatically). Omit to mirror ALL tables in the schema."
        ),
    )
    parser.add_argument(
        "--schema",
        default=None,
        help=(
            "Backend schema to reflect (default: BACKEND_DB_SCHEMA from .env/env, "
            "else the connection's default, usually public)."
        ),
    )
    parser.add_argument(
        "--include-django",
        action="store_true",
        help=(
            "Also mirror Django's own framework-internal tables (auth_group, "
            "auth_permission, django_migrations, django_content_type, "
            "django_admin_log, django_session, and their M2M join tables). "
            "Ignored if --tables is given explicitly. Default: excluded."
        ),
    )
    args = parser.parse_args()

    env = _BackendDBEnv()
    url = _sync_backend_url(env)
    schema = args.schema or (env.backend_db_schema.strip() or None)
    tables = _resolve_tables(url, args.tables, schema, args.include_django)
    raw = _run_sqlacodegen(url, tables, schema)
    code = _neutralize_unmapped_types(_rebind_to_backend_base(raw))
    code = GENERATED_HEADER + "\n" + code

    OUTPUT.write_text(code)
    _format_in_place(OUTPUT)
    scope = f"{len(args.tables)} requested table(s)" if args.tables else "all tables"
    if not args.tables and not args.include_django:
        scope += " (excluding Django-internal tables)"
    sys.stderr.write(f"wrote {OUTPUT.relative_to(REPO_ROOT)} ({scope})\n")


if __name__ == "__main__":
    main()
