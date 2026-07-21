"""Per-group fail-fast validator tests (FR-003).

Each test constructs the group (or Settings) directly — no `importlib.reload`,
no mutation of the process-wide `settings` singleton. The validator under
test is the group's own `model_validator(mode="after")` (or the root
`Settings` model_validator for cross-group checks), invoked by pydantic at
construction time. A misconfigured group therefore raises `ValidationError`
that names the offending field, regardless of what the import-time
singleton happens to be bound to.
"""

import pytest
from pydantic import ValidationError

from app.core.config import (
    BackendDbSettings,
    ChatModelSettings,
    EmbeddingsSettings,
    LangfuseSettings,
    LoggingSettings,
    MinerUSettings,
    OwnDbSettings,
    Settings,
    StorageSettings,
)

# ---------------------------------------------------------------------------
# Passing cases — one fully-valid construction per group, asserting no raise.
# ---------------------------------------------------------------------------


def test_chat_model_valid_construction_raises_nothing():
    ChatModelSettings(use_mock=True)  # all defaults are valid in mock mode


def test_embeddings_valid_construction_raises_nothing():
    EmbeddingsSettings()  # defaults are valid (api_key placeholder OK on its own)


def test_own_db_valid_construction_raises_nothing():
    OwnDbSettings(postgres_db="appdb", postgres_user="appuser", postgres_password="apppass")


def test_backend_db_valid_construction_raises_nothing():
    BackendDbSettings(host="h", name="n", user="u", password="p")


def test_storage_valid_construction_raises_nothing():
    StorageSettings(s3_bucket="b", s3_access_key="a", s3_secret_key="s")


def test_mineru_valid_construction_mocked_raises_nothing():
    MinerUSettings(use_mock=True)  # mocked: api_url not required


def test_mineru_valid_construction_real_raises_nothing():
    MinerUSettings(use_mock=False, api_url="http://mineru:8000")


def test_langfuse_valid_construction_when_disabled_raises_nothing():
    # enabled=False: host/public_key/secret_key may all stay at their empty defaults
    LangfuseSettings(enabled=False, host="", public_key="", secret_key="")


def test_langfuse_valid_construction_when_enabled_raises_nothing():
    LangfuseSettings()  # defaults already populate all three connection fields


def test_logging_valid_construction_raises_nothing():
    LoggingSettings(level="INFO")


def test_settings_valid_construction_with_token_raises_nothing():
    Settings(
        token="t",
        chat_model=ChatModelSettings(use_mock=True),
        own_db=OwnDbSettings(
            postgres_db="appdb", postgres_user="appuser", postgres_password="apppass"
        ),
        backend_db=BackendDbSettings(host="h", name="n", user="u", password="p"),
        storage=StorageSettings(s3_bucket="b", s3_access_key="a", s3_secret_key="s"),
    )


def _valid_other_groups(**overrides) -> Settings:
    """Construct Settings with every group valid except those in `overrides`.

    Lets each per-group failure test target exactly one validator without
    re-typing the full valid baseline every time.
    """
    defaults = dict(
        token="t",
        chat_model=ChatModelSettings(use_mock=True),
        own_db=OwnDbSettings(
            postgres_db="appdb", postgres_user="appuser", postgres_password="apppass"
        ),
        backend_db=BackendDbSettings(host="h", name="n", user="u", password="p"),
        storage=StorageSettings(s3_bucket="b", s3_access_key="a", s3_secret_key="s"),
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# own_db — empty db/user/password must fail (research.md §4).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,expected_field",
    [
        ({"postgres_db": ""}, "postgres_db"),
        ({"postgres_user": ""}, "postgres_user"),
        ({"postgres_password": ""}, "postgres_password"),
    ],
)
def test_own_db_rejects_empty_required_field(kwargs, expected_field):
    base = dict(postgres_db="appdb", postgres_user="appuser", postgres_password="apppass")
    base.update(kwargs)
    with pytest.raises(ValidationError) as exc_info:
        OwnDbSettings(**base)
    assert expected_field in str(exc_info.value) or "OWN_DB" in str(exc_info.value)


# ---------------------------------------------------------------------------
# backend_db — host/name/user/password required unconditionally (research.md §6).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,expected_field",
    [
        ({"host": ""}, "host"),
        ({"name": ""}, "name"),
        ({"user": ""}, "user"),
        ({"password": ""}, "password"),
    ],
)
def test_backend_db_rejects_empty_required_field(kwargs, expected_field):
    base = dict(host="h", name="n", user="u", password="p")
    base.update(kwargs)
    with pytest.raises(ValidationError) as exc_info:
        BackendDbSettings(**base)
    assert expected_field in str(exc_info.value) or "BACKEND_DB" in str(exc_info.value)


def test_backend_database_url_is_non_optional_str():
    """`backend_database_url` no longer returns `None` for unset config — the
    validator rejects that state at construction, so the property is always
    a real URL by the time any code reads it."""
    s = _valid_other_groups(
        backend_db=BackendDbSettings(host="h", name="n", user="u", password="p")
    )
    url = s.backend_database_url
    assert isinstance(url, str)
    assert "u:p@h:5432/n" in url


# ---------------------------------------------------------------------------
# chat_model / embeddings (cross-group, gated by chat_model.use_mock).
# ---------------------------------------------------------------------------


def test_settings_rejects_mock_api_key_when_chat_model_not_mocked():
    with pytest.raises(ValidationError, match="AI_SERVICE_CHAT_MODEL__OPENAI_API_KEY"):
        _valid_other_groups(
            chat_model=ChatModelSettings(use_mock=False, openai_api_key="__mock__"),
            embeddings=EmbeddingsSettings(api_key="sk-real-embedding-key"),
        )


def test_settings_rejects_mock_embedding_api_key_when_chat_model_not_mocked():
    with pytest.raises(ValidationError, match="AI_SERVICE_EMBEDDINGS__API_KEY"):
        _valid_other_groups(
            chat_model=ChatModelSettings(use_mock=False, openai_api_key="sk-real-chat-key"),
            embeddings=EmbeddingsSettings(api_key="__mock__"),
        )


def test_settings_accepts_real_keys_when_chat_model_not_mocked():
    # No raise — both api keys are real (non-placeholder) values.
    _valid_other_groups(
        chat_model=ChatModelSettings(use_mock=False, openai_api_key="sk-real-chat-key"),
        embeddings=EmbeddingsSettings(api_key="sk-real-embedding-key"),
    )


# ---------------------------------------------------------------------------
# storage — bucket/access_key/secret_key required (batched error message).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["s3_bucket", "s3_access_key", "s3_secret_key"])
def test_storage_rejects_empty_required_field(missing):
    base = dict(s3_bucket="b", s3_access_key="a", s3_secret_key="s")
    base[missing] = ""
    with pytest.raises(ValidationError, match="AI_SERVICE_STORAGE__S3"):
        StorageSettings(**base)


def test_storage_error_message_lists_all_missing_fields_together():
    """Spec FR-002/quickstart step 1: the failure identifies every missing
    field at once, not just the first one."""
    with pytest.raises(ValidationError) as exc_info:
        StorageSettings(s3_bucket="", s3_access_key="", s3_secret_key="")
    msg = str(exc_info.value)
    assert "AI_SERVICE_STORAGE__S3_BUCKET" in msg
    assert "AI_SERVICE_STORAGE__S3_ACCESS_KEY" in msg
    assert "AI_SERVICE_STORAGE__S3_SECRET_KEY" in msg


# ---------------------------------------------------------------------------
# mineru — api_url required unless use_mock.
# ---------------------------------------------------------------------------


def test_mineru_rejects_empty_api_url_when_not_mocked():
    with pytest.raises(ValidationError, match="AI_SERVICE_MINERU__API_URL"):
        MinerUSettings(use_mock=False, api_url="")


def test_mineru_accepts_empty_api_url_when_mocked():
    # mocked: api_url is not required.
    MinerUSettings(use_mock=True, api_url="")


# ---------------------------------------------------------------------------
# langfuse — host/public_key/secret_key required when enabled.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["host", "public_key", "secret_key"])
def test_langfuse_rejects_empty_connection_field_when_enabled(missing):
    base = dict(host="h", public_key="pk", secret_key="sk")
    base[missing] = ""
    with pytest.raises(ValidationError) as exc_info:
        LangfuseSettings(enabled=True, **base)
    assert "LANGFUSE" in str(exc_info.value)


def test_langfuse_accepts_empty_connection_fields_when_disabled():
    LangfuseSettings(enabled=False, host="", public_key="", secret_key="")


def test_langfuse_error_message_lists_all_missing_fields_when_enabled():
    with pytest.raises(ValidationError) as exc_info:
        LangfuseSettings(enabled=True, host="", public_key="", secret_key="")
    msg = str(exc_info.value)
    assert "AI_SERVICE_LANGFUSE__HOST" in msg
    assert "AI_SERVICE_LANGFUSE__PUBLIC_KEY" in msg
    assert "AI_SERVICE_LANGFUSE__SECRET_KEY" in msg


# ---------------------------------------------------------------------------
# logging — level must be one of the fixed severity set.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_level", ["", "trace", "verbose", "FATAL", "info "])
def test_logging_rejects_invalid_level(bad_level):
    with pytest.raises(ValidationError, match="AI_SERVICE_LOGGING__LEVEL"):
        LoggingSettings(level=bad_level)


@pytest.mark.parametrize("good_level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_logging_accepts_valid_level(good_level):
    LoggingSettings(level=good_level)


def test_logging_level_check_is_case_insensitive():
    # "info" (lowercase) is normalized inside the validator, not rejected.
    LoggingSettings(level="info")


# ---------------------------------------------------------------------------
# token — flat field on Settings, required (data-model.md "Ungrouped"). Named
# `token` (not `ai_service_token`) since `env_prefix="AI_SERVICE_"` already
# supplies that part of the resolved env var name, AI_SERVICE_TOKEN.
# ---------------------------------------------------------------------------


def test_settings_rejects_empty_token():
    with pytest.raises(ValidationError, match="AI_SERVICE_TOKEN"):
        _valid_other_groups(token="")
