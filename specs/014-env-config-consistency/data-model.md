# Phase 1 Data Model: Consistent, Fault-Tolerant Environment Configuration

## Summary

This feature adds **no tables, models, or migrations**. Its "entities" are the configuration groups themselves — `app/core/config.py`'s `Settings` class reorganized into nested `BaseModel` groups, per research.md §2. Each row below is one Key Entity from spec.md, expanded to field level.

## Configuration Group: Chat Model (`settings.chat_model`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `use_mock` | `bool` | `CHAT_MODEL__USE_MOCK` | `USE_MOCK_LLM` | Always has a default (`False`) |
| `openai_base_url` | `str` | `CHAT_MODEL__OPENAI_BASE_URL` | `OPENAI_BASE_URL` | Always has a default |
| `openai_api_key` | `SecretStr` | `CHAT_MODEL__OPENAI_API_KEY` | `OPENAI_API_KEY` | **Yes, when `use_mock=False`** |
| `model_name` | `str` | `CHAT_MODEL__MODEL_NAME` | `MODEL_NAME` | Always has a default |
| `normalization_max_parallel_chunks` | `int` | `CHAT_MODEL__NORMALIZATION_MAX_PARALLEL_CHUNKS` | `NORMALIZATION_MAX_PARALLEL_CHUNKS` | Always has a default |
| `normalization_chunk_max_tokens` | `int` | `CHAT_MODEL__NORMALIZATION_CHUNK_MAX_TOKENS` | `NORMALIZATION_CHUNK_MAX_TOKENS` | Always has a default |

Named `chat_model`, not `llm` — this group is specifically the chat/completion model's configuration, distinct from `embeddings` below even though both are technically "an LLM-adjacent API." Group renamed from the earlier `llm`/`LLM__*` naming during task planning; the mock field briefly went through a `mock_enabled` rename during that same pass but was reverted back to `use_mock` post-implementation (research.md §8).

Validation rule (root-level, spans into `embeddings` — research.md §3): `use_mock=False` requires `openai_api_key` not empty and not the `"__mock__"` sentinel.

## Configuration Group: Embeddings (`settings.embeddings`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `base_url` | `str` | `EMBEDDINGS__BASE_URL` | `EMBEDDING_BASE_URL` | Always has a default |
| `api_key` | `SecretStr` | `EMBEDDINGS__API_KEY` | `EMBEDDING_API_KEY` | **Yes, when `chat_model.use_mock=False`** |
| `model_name` | `str` | `EMBEDDINGS__MODEL_NAME` | `EMBEDDING_MODEL_NAME` | Always has a default |
| `dimensions` | `int` | `EMBEDDINGS__DIMENSIONS` | `EMBEDDING_DIMENSIONS` | Always has a default |

Validation rule: same root-level check as `chat_model`, gated by `chat_model.use_mock` (there is deliberately no separate `embeddings`-level mock flag — this preserves today's behavior exactly).

## Configuration Group: Own database (`settings.own_db`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `postgres_host` | `str` | `OWN_DB__POSTGRES_HOST` | `POSTGRES_HOST` | Always has a default (`"postgres"`) |
| `postgres_port` | `str` | `OWN_DB__POSTGRES_PORT` | `POSTGRES_PORT` | Always has a default (`"5432"`) |
| `postgres_db` | `str` | `OWN_DB__POSTGRES_DB` | `POSTGRES_DB` | **Yes** (research.md §4 — new) |
| `postgres_user` | `str` | `OWN_DB__POSTGRES_USER` | `POSTGRES_USER` | **Yes** (new) |
| `postgres_password` | `SecretStr` | `OWN_DB__POSTGRES_PASSWORD` | `POSTGRES_PASSWORD` | **Yes** (new) |

Validation rule (new — this group had none before): `postgres_db`/`postgres_user`/`postgres_password` MUST be non-empty; their previous fake-but-plausible defaults (`"appdb"`/`"appuser"`/`"apppass"`) are removed in favor of empty defaults that trip this check, matching every other required group's convention.

## Configuration Group: Backend database (`settings.backend_db`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `host` | `str` | `BACKEND_DB__HOST` | `BACKEND_DB_HOST` | **Yes** (was optional — resolved clarification, research.md §6) |
| `port` | `str` | `BACKEND_DB__PORT` | `BACKEND_DB_PORT` | Always has a default (`"5432"`) |
| `name` | `str` | `BACKEND_DB__NAME` | `BACKEND_DB_NAME` | **Yes** (was optional) |
| `user` | `str` | `BACKEND_DB__USER` | `BACKEND_DB_USER` | **Yes** (was optional) |
| `password` | `SecretStr` | `BACKEND_DB__PASSWORD` | `BACKEND_DB_PASSWORD` | **Yes** (was optional) |

Validation rule: same empty-check pattern as `own_db`. `Settings.backend_database_url` changes from `str | None` to `str` (no longer conditional — every construction of `Settings` now guarantees these are set, or fails first).

## Configuration Group: Storage (`settings.storage`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `s3_bucket` | `str` | `STORAGE__S3_BUCKET` | `STORAGE_S3_BUCKET` | **Yes** (unchanged) |
| `s3_endpoint_url` | `str` | `STORAGE__S3_ENDPOINT_URL` | `STORAGE_S3_ENDPOINT_URL` | No — empty ⇒ real AWS S3 (unchanged, intentionally optional) |
| `s3_region` | `str` | `STORAGE__S3_REGION` | `STORAGE_S3_REGION` | Always has a default |
| `s3_access_key` | `SecretStr` | `STORAGE__S3_ACCESS_KEY` | `STORAGE_S3_ACCESS_KEY` | **Yes** (unchanged) |
| `s3_secret_key` | `SecretStr` | `STORAGE__S3_SECRET_KEY` | `STORAGE_S3_SECRET_KEY` | **Yes** (unchanged) |
| `s3_use_path_style` | `bool` | `STORAGE__S3_USE_PATH_STYLE` | `STORAGE_S3_USE_PATH_STYLE` | Always has a default |
| `s3_ocr_bucket` | `str` | `STORAGE__S3_OCR_BUCKET` | `STORAGE_S3_OCR_BUCKET` | Always has a default |

Validation rule: unchanged from today (`s3_bucket`/`s3_access_key`/`s3_secret_key` non-empty), just moved onto this group's own validator.

## Configuration Group: MinerU (`settings.mineru`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `use_mock` | `bool` | `MINERU__USE_MOCK` | `USE_MOCK_MINERU` | Always has a default |
| `api_url` | `str` | `MINERU__API_URL` | `MINERU_API_URL` | **Yes, when `use_mock=False`** (unchanged) |
| `api_key` | `SecretStr` | `MINERU__API_KEY` | `MINERU_API_KEY` | No — optional header (unchanged) |

Field briefly renamed from `use_mock` to `mock_enabled` during task planning, mirroring the `chat_model` group's naming, then reverted back to `use_mock` post-implementation (research.md §8) — same env var name as before that whole naming pass, `MINERU__USE_MOCK`.

## Configuration Group: Langfuse (`settings.langfuse`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `enabled` | `bool` | `LANGFUSE__ENABLED` | `LANGFUSE_ENABLED` | Always has a default |
| `host` | `str` | `LANGFUSE__HOST` | `LANGFUSE_HOST` | **Yes, when `enabled=True`** (unchanged) |
| `public_key` | `str` | `LANGFUSE__PUBLIC_KEY` | `LANGFUSE_PUBLIC_KEY` | **Yes, when `enabled=True`** (unchanged) |
| `secret_key` | `SecretStr` | `LANGFUSE__SECRET_KEY` | `LANGFUSE_SECRET_KEY` | **Yes, when `enabled=True`** (unchanged) |

## Configuration Group: Logging (`settings.logging`)

| Field | Type | New env var | Old env var | Required? |
|---|---|---|---|---|
| `level` | `str` | `LOGGING__LEVEL` | `LOG_LEVEL` | Always has a default; validated against the fixed severity set |
| `debug_include_raw_content` | `bool` | `LOGGING__DEBUG_INCLUDE_RAW_CONTENT` | `LOG_DEBUG_INCLUDE_RAW_CONTENT` | Always has a default |

## Ungrouped: Auth

| Field | Type | Env var (unchanged) | Required? |
|---|---|---|---|
| `ai_service_token` | `SecretStr` | `AI_SERVICE_TOKEN` | **Yes** (unchanged) |

Deliberately not grouped (research.md §2) — the sole field concerned with service-to-service auth, called out by name in Constitution Principle II; wrapping it in a one-field `AuthSettings` group adds a layer with no organizational benefit.

## Entity: Deterministic Override

Not a `Settings` field — a compose-file-level concept (`docker-compose.prod.yml`'s `environment:` block). No data-model representation; documented in contracts/env-var-contract.md instead since it's an interface between compose files, not application state.

## State Transitions

None — configuration is read once at process startup (`settings = Settings()` at import time) and is immutable for the process lifetime, unchanged from today.
