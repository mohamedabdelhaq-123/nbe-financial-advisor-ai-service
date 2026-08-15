# Convenience targets for the NBE AI service. Run `make help` for the list.

.PHONY: help gen-backend-models dev-up dev-down prod-build prod-up prod-down redteam redteam-verbose redteam-llm redteam-llm-only

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# The compose files now live in nbe-financial-advisor-backend/deploy/ and are
# the single consolidated stack (postgres, redis, seaweedfs, backend,
# celery-worker, mock-bank-oauth/sync, ai-service, frontend) — there's no
# more ai-service-only compose project to join an external network from.
# `make dev-up`/`prod-up` here are thin aliases onto that stack, run from
# this repo for convenience. Langfuse observability isn't wired back in yet
# (see compose/langfuse/docker-compose.yml — currently unused).
DEPLOY_DIR := ../nbe-financial-advisor-backend/deploy
DEV_COMPOSE := docker compose -f $(DEPLOY_DIR)/docker-compose.dev.yml
PROD_COMPOSE := docker compose -f $(DEPLOY_DIR)/docker-compose.prod.yml --env-file $(DEPLOY_DIR)/.env

dev-up: ## Start the full dev stack (backend, ai-service, frontend, infra) from nbe-financial-advisor-backend/deploy
	$(DEV_COMPOSE) up --build

dev-down: ## Stop the dev stack
	$(DEV_COMPOSE) down -v

prod-build: ## Build the hardened prod images
	$(PROD_COMPOSE) build

prod-up: ## Start the full prod stack, detached
	$(PROD_COMPOSE) up --build -d

prod-down: ## Stop the prod stack
	$(PROD_COMPOSE) down

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
