"""
Application configuration.

Settings are instantiated once at import time and fail fast (raise) when a
required secret is missing or left at a placeholder value — a misconfigured
service must never boot into an insecure or half-wired state.

Each settings group validates itself via its own `model_validator(mode="after")`;
checks spanning two groups live on the root `Settings` model_validator instead,
since only it has both groups in scope.
"""

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ChatModelSettings(BaseModel):
    use_mock: bool = False
    # Required only when use_mock is False; safe to omit in mock mode.
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr = SecretStr("__mock__")  # placeholder — unused in mock mode
    model_name: str = "gpt-4o-mini"
    # How many chunks statement normalization processes concurrently. Keep
    # low for a constrained per-minute token budget; raise once the
    # configured provider/tier can absorb more concurrent throughput.
    normalization_max_parallel_chunks: int = Field(default=1, ge=1)
    # Per-chunk completion token ceiling for statement normalization.
    # Reasoning models may need this raised — they spend a variable share of
    # the budget on hidden reasoning tokens before emitting the actual JSON.
    # Tune per provider/model rather than changing the default globally.
    normalization_chunk_max_tokens: int = 4096


class EmbeddingsSettings(BaseModel):
    # Independent from the chat model base URL/key — the embedding provider is not
    # guaranteed to live at the same endpoint (e.g. chat pointed at a self-hosted
    # vLLM instance that serves no embedding model, embeddings kept on OpenAI proper).
    # Required only when chat_model.use_mock is False; safe to omit in mock mode.
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr = SecretStr("__mock__")  # placeholder — unused in mock mode
    model_name: str = "text-embedding-3-small"
    # Must stay 768 unless AiProblemStatement.embedding
    # (app/features/recommendations/models.py) is migrated in lockstep — a
    # caller needing a different size passes it explicitly rather than
    # changing this.
    dimensions: int = Field(default=768, ge=1)


class OwnDbSettings(BaseModel):
    # This service owns and migrates only this database.
    postgres_host: str = "postgres"
    postgres_port: str = "5432"
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def _require_credentials(self) -> "OwnDbSettings":
        missing = [
            name
            for name, value in (
                ("AI_SERVICE_OWN_DB__POSTGRES_DB", self.postgres_db),
                ("AI_SERVICE_OWN_DB__POSTGRES_USER", self.postgres_user),
                ("AI_SERVICE_OWN_DB__POSTGRES_PASSWORD", self.postgres_password.get_secret_value()),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} must be set. "
                "This service owns and migrates this database — it cannot boot "
                "against placeholder credentials."
            )
        return self


class BackendDbSettings(BaseModel):
    # Required unconditionally — access uses a dedicated read-only Postgres role.
    host: str = ""
    port: str = "5432"
    name: str = ""
    user: str = ""
    password: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def _require_credentials(self) -> "BackendDbSettings":
        missing = [
            name
            for name, value in (
                ("AI_SERVICE_BACKEND_DB__HOST", self.host),
                ("AI_SERVICE_BACKEND_DB__NAME", self.name),
                ("AI_SERVICE_BACKEND_DB__USER", self.user),
                ("AI_SERVICE_BACKEND_DB__PASSWORD", self.password.get_secret_value()),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} must be set. "
                "Set these to the backend's read-only role credentials to "
                "enable read access to backend-owned tables."
            )
        return self


class StorageSettings(BaseModel):
    # Targets any S3-compatible endpoint (e.g. SeaweedFS); the bucket must
    # already exist — this service never creates it.
    s3_bucket: str = ""
    s3_endpoint_url: str = ""  # empty => real AWS S3; set for SeaweedFS etc.
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_use_path_style: bool = True
    # Dedicated bucket for statement OCR/extraction output (ingestion slice). Kept
    # separate from s3_bucket so this feature's output location never
    # implicitly depends on what any other feature configures that setting to mean.
    s3_ocr_bucket: str = "pfm-statements-ocr"

    @model_validator(mode="after")
    def _require_bucket_credentials(self) -> "StorageSettings":
        missing = [
            name
            for name, value in (
                ("AI_SERVICE_STORAGE__S3_BUCKET", self.s3_bucket),
                ("AI_SERVICE_STORAGE__S3_ACCESS_KEY", self.s3_access_key.get_secret_value()),
                ("AI_SERVICE_STORAGE__S3_SECRET_KEY", self.s3_secret_key.get_secret_value()),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} must be set. "
                "Point them at an existing bucket on an S3-compatible endpoint "
                "(e.g. SeaweedFS) — this service never creates the bucket itself."
            )
        return self


class MinerUSettings(BaseModel):
    use_mock: bool = False
    api_url: str = ""
    api_key: SecretStr = SecretStr("")  # sent as the X-Api-Key header; optional

    @model_validator(mode="after")
    def _require_api_url_when_not_mocked(self) -> "MinerUSettings":
        if not self.use_mock and not self.api_url:
            raise ValueError(
                "AI_SERVICE_MINERU__API_URL must be set when AI_SERVICE_MINERU__USE_MOCK is "
                "false. Set AI_SERVICE_MINERU__USE_MOCK=1 to run without a reachable MinerU "
                "instance."
            )
        return self


class LangfuseSettings(BaseModel):
    # Misconfigured tracing fails open (disables itself) rather than
    # blocking startup — see app/core/observability.py. Defaults match the
    # local self-hosted Langfuse stack; point these at a cloud-hosted
    # instance instead, or set enabled=False to disable outright.
    enabled: bool = True
    host: str = "http://langfuse-web:3000"
    public_key: str = "pk-lf-00000000-0000-0000-0000-000000000000"
    secret_key: SecretStr = SecretStr("sk-lf-00000000-0000-0000-0000-000000000000")

    @model_validator(mode="after")
    def _require_connection_when_enabled(self) -> "LangfuseSettings":
        if not self.enabled:
            return self
        missing = [
            name
            for name, value in (
                ("AI_SERVICE_LANGFUSE__HOST", self.host),
                ("AI_SERVICE_LANGFUSE__PUBLIC_KEY", self.public_key),
                ("AI_SERVICE_LANGFUSE__SECRET_KEY", self.secret_key.get_secret_value()),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} must be set when AI_SERVICE_LANGFUSE__ENABLED is true. "
                "Set AI_SERVICE_LANGFUSE__ENABLED=false to disable tracing instead."
            )
        return self


class LoggingSettings(BaseModel):
    # Minimum severity emitted; validated below (fail fast on an invalid value
    # rather than silently falling back to a default).
    level: str = "INFO"
    # When true, LLM prompt/completion and DB query content MAY be logged at
    # DEBUG severity for local troubleshooting. MUST NEVER be enabled in
    # production — see app/core/logging.py.
    debug_include_raw_content: bool = False

    @model_validator(mode="after")
    def _validate_level(self) -> "LoggingSettings":
        if self.level.upper() not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"AI_SERVICE_LOGGING__LEVEL={self.level!r} is invalid. "
                f"Must be one of: {', '.join(sorted(_VALID_LOG_LEVELS))}."
            )
        return self


class Settings(BaseSettings):
    # ── auth ───────────────────────────────────────────────────────────────
    # Shared secret between the Django backend and this service. Not
    # `ai_service_token` — the `AI_SERVICE_` env_prefix below already supplies
    # that part, so the resolved env var stays AI_SERVICE_TOKEN, not a
    # redundant AI_SERVICE_AI_SERVICE_TOKEN.
    token: SecretStr = SecretStr("")

    # ── grouped configuration ──────────────────────────────────────────────
    # No class-level defaults for groups with required-field validators —
    # those default instances would fail their own validation. Populated
    # instead from environment variables; every real deployment supplies
    # them, and tests fabricate placeholders for offline runs.
    chat_model: ChatModelSettings = Field(default_factory=ChatModelSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    own_db: OwnDbSettings
    backend_db: BackendDbSettings
    storage: StorageSettings
    mineru: MinerUSettings = Field(default_factory=MinerUSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    model_config = SettingsConfigDict(
        env_prefix="AI_SERVICE_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    @model_validator(mode="after")
    def _enforce_cross_group_requirements(self) -> "Settings":
        # chat_model.use_mock gates BOTH chat_model.openai_api_key and
        # embeddings.api_key — there is no separate embeddings-level mock flag.
        if not self.chat_model.use_mock:
            if self.chat_model.openai_api_key.get_secret_value() == "__mock__":
                raise ValueError(
                    "AI_SERVICE_CHAT_MODEL__OPENAI_API_KEY must be set when "
                    "AI_SERVICE_CHAT_MODEL__USE_MOCK is false. Set "
                    "AI_SERVICE_CHAT_MODEL__USE_MOCK=1 in .env to run fully offline."
                )
            if self.embeddings.api_key.get_secret_value() == "__mock__":
                raise ValueError(
                    "AI_SERVICE_EMBEDDINGS__API_KEY must be set when "
                    "AI_SERVICE_CHAT_MODEL__USE_MOCK is false. Set "
                    "AI_SERVICE_CHAT_MODEL__USE_MOCK=1 in .env to run fully offline."
                )

        if not self.token.get_secret_value():
            raise ValueError(
                "AI_SERVICE_TOKEN must be set. "
                'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return self

    @property
    def own_database_url(self) -> str:
        """Async SQLAlchemy URL for the service-owned (read-write) database."""
        return (
            f"postgresql+asyncpg://{self.own_db.postgres_user}:"
            f"{self.own_db.postgres_password.get_secret_value()}"
            f"@{self.own_db.postgres_host}:{self.own_db.postgres_port}/{self.own_db.postgres_db}"
        )

    @property
    def backend_database_url(self) -> str:
        """Async SQLAlchemy URL for the backend-owned (read-only) database.

        Always buildable — BackendDbSettings' validator rejects empty
        credentials at construction time.
        """
        return (
            f"postgresql+asyncpg://{self.backend_db.user}:"
            f"{self.backend_db.password.get_secret_value()}"
            f"@{self.backend_db.host}:{self.backend_db.port}/{self.backend_db.name}"
        )


# Instantiated once at import time — raises immediately if misconfigured.
# `type: ignore[call-arg]`: mypy sees own_db/backend_db/storage as required
# (no class-level default), but pydantic-settings populates them from env
# vars at runtime — the construction has no positional args in source.
settings = Settings()  # type: ignore[call-arg]
