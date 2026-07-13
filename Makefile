# Convenience targets for the NBE AI service. Run `make help` for the list.

.PHONY: help gen-backend-models dev-up dev-down prod-build prod-smoke

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

dev-down: ## Stop the dev stack
	$(COMPOSE) -f compose/docker-compose.dev.yml down

prod-build: ## Build the hardened prod image
	$(COMPOSE) -f compose/docker-compose.prod.yml build

prod-smoke: ## Boot the prod image standalone (fully mocked) and check its healthcheck
	$(COMPOSE) -f compose/docker-compose.prod.yml up --build --abort-on-container-exit

# Regenerate the read-only backend mirror models directly from the live backend DB.
# Requires BACKEND_DB_* env (a READ-ONLY role). Optionally scope to specific tables:
#   make gen-backend-models TABLES="auth_user accounts_account"
#   make gen-backend-models          # omit TABLES to mirror ALL tables
gen-backend-models: ## Regenerate backend mirror models from the live read-only backend DB (TABLES="t1 t2" to scope)
	uv run --group codegen python scripts/gen_backend_models.py $(if $(TABLES),--tables $(TABLES),)
