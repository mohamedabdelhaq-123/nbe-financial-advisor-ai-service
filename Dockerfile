# syntax=docker/dockerfile:1
FROM astral/uv:python3.12-bookworm-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
	PYTHONDONTWRITEBYTECODE=1 \
	UV_COMPILE_BYTECODE=1 \
	UV_LINK_MODE=copy \
	PATH="/app/.venv/bin:$PATH"

# Install runtime deps first (cached until the lockfile changes).
COPY pyproject.toml uv.lock ./

# ---- dev: full deps (incl. dev/test groups), hot reload, bind-mount friendly ----
FROM base AS dev
RUN uv sync --frozen --no-install-project
COPY . .
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

# ---- prod-deps: runtime-only deps in their own layer ----
FROM base AS prod-deps
RUN uv sync --frozen --no-dev --no-install-project

# ---- prod: hardened runtime image, non-root, no dev deps ----
FROM python:3.12-slim AS prod
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
	PYTHONDONTWRITEBYTECODE=1 \
	PATH="/app/.venv/bin:$PATH"

COPY --from=prod-deps --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . .

USER appuser
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
	CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
