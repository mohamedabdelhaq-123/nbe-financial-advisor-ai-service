# Convenience targets for the NBE AI service. Run `make help` for the list.

.PHONY: help gen-backend-models dev-up dev-up-observability dev-down prod-build prod-up prod-down redteam redteam-verbose redteam-llm redteam-llm-only

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --env-file points variable substitution (${POSTGRES_PASSWORD:-...} etc.) at
# the repo-root .env explicitly — Compose would otherwise look for one next
# to the first -f file (compose/), which doesn't exist. (Deliberately not
# --project-directory: that also redirects `extends:` file lookups, which
# breaks the mineru-server extends in compose/docker-compose.yml.)
COMPOSE := docker compose --env-file .env -f compose/docker-compose.yml

# Requires the backend repo's own dev stack (postgres + seaweedfs) already
# running, so the nbe-dev network and those hostnames exist.
dev-up: ## Start the ai-service in dev mode (hot reload, joins nbe-dev network)
	$(COMPOSE) -f compose/docker-compose.dev.yml up --build

# Same as dev-up, plus the local self-hosted Langfuse stack (6 extra
# containers, gated behind the "observability" compose profile — off by
# default so plain `dev-up`/`prod-up` stay free of them). Auto-provisions
# its own project/API keys on first boot; see .env.example's LANGFUSE_* vars.
dev-up-observability: ## Start the dev stack plus local self-hosted Langfuse (compose profile "observability")
	$(COMPOSE) -f compose/docker-compose.dev.yml --profile observability up --build

# --profile observability here too, so this also tears down the Langfuse
# containers if dev-up-observability was used — a no-op otherwise.
dev-down: ## Stop the dev stack (including Langfuse, if it was started)
	$(COMPOSE) -f compose/docker-compose.dev.yml --profile observability down -v

prod-build: ## Build the hardened prod image
	$(COMPOSE) -f compose/docker-compose.prod.yml build

# Requires the nbe-prod network to already exist (see compose/docker-compose.prod.yml
# header) and ../.env to hold real production credentials.
prod-up: ## Start the ai-service in production mode (joins nbe-prod network, detached)
	$(COMPOSE) -f compose/docker-compose.prod.yml up --build -d

prod-down: ## Stop the production ai-service container
	$(COMPOSE) -f compose/docker-compose.prod.yml down

# Regenerate the read-only backend mirror models directly from the live backend DB.
# Requires BACKEND_DB_* env (a READ-ONLY role). Optionally scope to specific tables:
#   make gen-backend-models TABLES="auth_user accounts_account"
#   make gen-backend-models          # omit TABLES to mirror ALL tables
gen-backend-models: ## Regenerate backend mirror models from the live read-only backend DB (TABLES="t1 t2" to scope)
	uv run --group codegen python scripts/gen_backend_models.py $(if $(TABLES),--tables $(TABLES),)

# ── Red-team / AI-security suite (see redteam/README.md) ────────────────────
# Fully offline and deterministic by default: no real LLM/DB/network calls,
# forced regardless of ambient env vars (see redteam/conftest.py's module
# docstring — this matters e.g. inside the docker-compose dev container,
# whose env_file sets real, non-mock provider credentials). Model-dependent
# scenarios are skipped unless AI_SERVICE_REDTEAM_ENABLE_LLM=1 and a real
# AI_SERVICE_CHAT_MODEL__* provider are both set — never run implicitly by
# `make redteam`, `pytest`, or any other target here.
#
# No `make` inside the running dev container's ai-service image — run the
# underlying command directly there instead, e.g.:
#   docker compose exec ai-service uv run pytest redteam -q
redteam: ## Run the deterministic red-team suite; (re)writes redteam/reports/FINDINGS.md
	uv run pytest redteam -q

redteam-verbose: ## Same as `redteam`, with per-test output
	uv run pytest redteam -v

redteam-llm: ## Run the FULL suite (deterministic + model-dependent; needs a real LLM provider configured)
	AI_SERVICE_REDTEAM_ENABLE_LLM=1 uv run pytest redteam -v

redteam-llm-only: ## Model-dependent scenarios only, skipping the deterministic suite (faster iteration)
	AI_SERVICE_REDTEAM_ENABLE_LLM=1 uv run pytest redteam -v -m redteam_llm
