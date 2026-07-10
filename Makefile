# Convenience targets for the NBE AI service. Run `make help` for the list.

.PHONY: help gen-backend-models

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# Regenerate the read-only backend mirror models directly from the live backend DB.
# Requires BACKEND_DB_* env (a READ-ONLY role). Optionally scope to specific tables:
#   make gen-backend-models TABLES="auth_user accounts_account"
#   make gen-backend-models          # omit TABLES to mirror ALL tables
gen-backend-models: ## Regenerate backend mirror models from the live read-only backend DB (TABLES="t1 t2" to scope)
	uv run --group codegen python scripts/gen_backend_models.py $(if $(TABLES),--tables $(TABLES),)
