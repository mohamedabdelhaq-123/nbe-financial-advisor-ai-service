"""Red-team / AI-security test suite for the AI service.

Isolated from `tests/` (production correctness suite) and never collected by
the default `pytest tests` invocation used in CI (see `pyproject.toml`'s
`testpaths = ["tests"]`). Run explicitly via `make redteam` or
`uv run pytest redteam`. See `redteam/README.md`.
"""
