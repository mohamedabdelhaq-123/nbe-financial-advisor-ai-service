# Contract: Environment Variable Naming & Ownership

This feature exposes no new HTTP endpoints. Its interface to the rest of the system is the set of environment variable names `Settings` reads, which repository/environment gets to define their values, and which files must change together when a name changes. Documented here as the contract a developer, CI job, or deploy operator needs — full field-by-field detail lives in data-model.md, rationale in research.md.

## 1. Naming convention

Every variable name is `GROUP__FIELD` (double underscore, matching `pydantic-settings`' `env_nested_delimiter="__"`), uppercase, except `AI_SERVICE_TOKEN` which stays flat (data-model.md, "Ungrouped: Auth"). See data-model.md's per-group tables for the full old-name → new-name mapping.

**Contract guarantee**: for any given setting, there is exactly one env var name that sets it, and exactly one file per environment that is the authoritative place to set that value:

| Environment | Authoritative source | Mechanism |
|---|---|---|
| Local development / `make dev-up*` | This repo's `.env` (gitignored, copied from `.env.example`) | `env_file: ../.env` on the `ai-service` service in `compose/docker-compose.yml` |
| `make prod-smoke` (local/CI hardened-image gate) | `compose/docker-compose.prod.yml`'s own `environment:` block | Deterministic override (research.md §1) — intentionally bypasses `.env` |
| CI (`.github/workflows/ci.yml` + `tests/conftest.py`) | Workflow `env:` block + `conftest.py`'s `os.environ.setdefault(...)` fabricated placeholders | Neither reads `.env` |
| Real production deployment | `nbe-financial-advisor-backend/deploy/.env` (that repo's own, separate file) | `nbe-financial-advisor-backend/deploy/docker-compose.yml`'s `ai-service` `environment:` block (literal `${VAR:-default}` entries, no `env_file`) |

No two rows above may declare conflicting values for the same running instance — each environment fully owns its own source.

## 2. Required vs. optional, by group

| Group | Required fields (fail startup if missing/placeholder) | Optional fields (have a working default) |
|---|---|---|
| `chat_model` | `openai_api_key` (only when `use_mock=False`) | everything else |
| `embeddings` | `api_key` (only when `chat_model.use_mock=False`) | everything else |
| `own_db` | `postgres_db`, `postgres_user`, `postgres_password` | `postgres_host`, `postgres_port` |
| `backend_db` | `host`, `name`, `user`, `password` (now unconditional — research.md §6) | `port` |
| `storage` | `s3_bucket`, `s3_access_key`, `s3_secret_key` | `s3_endpoint_url`, `s3_region`, `s3_use_path_style`, `s3_ocr_bucket` |
| `mineru` | `api_url` (only when `use_mock=False`) | `api_key` (optional header even when not mocked) |
| `langfuse` | `host`, `public_key`, `secret_key` (only when `enabled=True`) | `enabled` itself |
| `logging` | none | `level` (validated against a fixed set if set), `debug_include_raw_content` |
| (ungrouped) | `ai_service_token` | — |

**Contract guarantee**: every "required" cell above produces an immediate `ValidationError` at `Settings()` construction (process startup) naming the specific field, never a deferred failure at first use (spec FR-002, SC-002).

## 3. Secret masking

Every field marked `SecretStr` in data-model.md's per-group tables renders as a fixed masked placeholder from `str()`/`repr()`. Code that needs the real value MUST call `.get_secret_value()` explicitly — this is the only sanctioned way to extract it. The full list of call sites that do this is enumerated in research.md §5 / plan.md's Project Structure; that list is the complete set as of this feature — a new credential field added later MUST be typed `SecretStr` and MUST have its consuming call site call `.get_secret_value()` explicitly, or it will send the literal masked text instead of the real secret (a functional failure, not just a lint gap).

## 4. Cross-repo rename obligation

**Contract guarantee**: this repo's `.env.example` and `nbe-financial-advisor-backend/deploy/docker-compose.yml` + `.env.example` change together, in the same effort, whenever a `GROUP__FIELD` name changes. This repo's own `compose/docker-compose.prod.yml` also renames its pinned override keys to match (research.md §7). There is no backward-compatible dual-name period — old flat names stop being recognized the moment this lands, everywhere.
