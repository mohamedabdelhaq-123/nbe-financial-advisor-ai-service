"""
Application configuration.

Settings are instantiated once at import time and fail fast (raise) when a
required secret is missing or left at a placeholder value — a misconfigured
service must never boot into an insecure or half-wired state.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── LLM ────────────────────────────────────────────────────────────────
    use_mock_llm: bool = False
    # Required only when use_mock_llm is False; safe to omit in mock mode.
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = "__mock__"  # placeholder — unused in mock mode
    model_name: str = "gpt-4o-mini"

    # ── auth ───────────────────────────────────────────────────────────────
    # Shared secret between the Django backend and this service.
    ai_service_token: str = ""

    # ── own database (READ-WRITE) ──────────────────────────────────────────
    # This service owns and migrates only this database.
    postgres_host: str = "postgres"
    postgres_port: str = "5432"
    postgres_db: str = "appdb"
    postgres_user: str = "appuser"
    postgres_password: str = "apppass"

    # ── backend database (READ-ONLY) ───────────────────────────────────────
    # Populated only where a live backend is reachable; empty by default so
    # unit tests and CI need no backend. Access must use a read-only DB role.
    backend_db_host: str = ""
    backend_db_port: str = "5432"
    backend_db_name: str = ""
    backend_db_user: str = ""
    backend_db_password: str = ""

    # ── storage (S3-compatible object storage) ─────────────────────────────
    # Targets any S3-compatible endpoint (e.g. SeaweedFS); the bucket must
    # already exist — this service never creates it.
    storage_s3_bucket: str = ""
    storage_s3_endpoint_url: str = ""  # empty => real AWS S3; set for SeaweedFS etc.
    storage_s3_region: str = "us-east-1"
    storage_s3_access_key: str = ""
    storage_s3_secret_key: str = ""
    storage_s3_use_path_style: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def own_database_url(self) -> str:
        """Async SQLAlchemy URL for the service-owned (read-write) database."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def backend_database_url(self) -> str | None:
        """Async SQLAlchemy URL for the backend-owned (read-only) database.

        Returns None when the backend DB is not configured, so the read-only
        engine is created lazily only where it is actually reachable.
        """
        if not (self.backend_db_host and self.backend_db_name and self.backend_db_user):
            return None
        return (
            f"postgresql+asyncpg://{self.backend_db_user}:{self.backend_db_password}"
            f"@{self.backend_db_host}:{self.backend_db_port}/{self.backend_db_name}"
        )


# Instantiated once at import time — raises immediately if misconfigured.
settings = Settings()

if not settings.use_mock_llm and settings.openai_api_key == "__mock__":
    raise RuntimeError(
        "OPENAI_API_KEY must be set when USE_MOCK_LLM is false. "
        "Set USE_MOCK_LLM=1 in .env to run fully offline."
    )

if not settings.ai_service_token:
    raise RuntimeError(
        "AI_SERVICE_TOKEN must be set. "
        'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
    )

_missing_storage_fields = [
    name
    for name, value in (
        ("STORAGE_S3_BUCKET", settings.storage_s3_bucket),
        ("STORAGE_S3_ACCESS_KEY", settings.storage_s3_access_key),
        ("STORAGE_S3_SECRET_KEY", settings.storage_s3_secret_key),
    )
    if not value
]
if _missing_storage_fields:
    raise RuntimeError(
        f"{', '.join(_missing_storage_fields)} must be set. "
        "Point them at an existing bucket on an S3-compatible endpoint "
        "(e.g. SeaweedFS) — this service never creates the bucket itself."
    )
