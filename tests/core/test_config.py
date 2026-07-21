"""Fail-fast configuration tests."""

import importlib
import json

import pytest


def test_invalid_log_level_raises(monkeypatch):
    """Config must fail fast on an unrecognized LOG_LEVEL value."""
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")

    import app.core.config as cfg

    with pytest.raises(RuntimeError, match="LOG_LEVEL"):
        importlib.reload(cfg)


def test_debug_raw_content_flag_emits_startup_warning(monkeypatch, capfd):
    """FR-011: enabling raw-content debug logging must never be silent.

    Monkeypatches the `settings` object as bound *inside* `app.core.logging`
    rather than re-importing from `app.core.config` — a prior test in this
    module may have `importlib.reload()`ed `app.core.config`, which rebinds
    its own `settings` name to a new instance without updating the reference
    other already-imported modules (like `app.core.logging`) are still
    holding, so the two names can point at different objects.
    """
    from app.core import logging as app_logging

    monkeypatch.setattr(app_logging.settings, "log_debug_include_raw_content", True)
    app_logging.configure()

    out, _ = capfd.readouterr()
    entries = [json.loads(line) for line in out.strip().splitlines() if line]
    warnings = [e for e in entries if e.get("event") == "raw_content_logging_enabled"]
    assert len(warnings) == 1
    assert warnings[0]["level"] == "warning"


def test_missing_api_key_raises_when_mock_disabled(monkeypatch):
    """Config must fail fast if USE_MOCK_LLM=false and no real key is set."""
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "__mock__")

    import app.core.config as cfg

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        importlib.reload(cfg)


def test_missing_embedding_api_key_raises_when_mock_disabled(monkeypatch):
    """Config must fail fast if USE_MOCK_LLM=false and no real embedding key is set."""
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-chat-key")
    monkeypatch.setenv("EMBEDDING_API_KEY", "__mock__")

    import app.core.config as cfg

    with pytest.raises(RuntimeError, match="EMBEDDING_API_KEY"):
        importlib.reload(cfg)


def test_missing_token_raises(monkeypatch):
    """Config must fail fast if AI_SERVICE_TOKEN is unset."""
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setenv("AI_SERVICE_TOKEN", "")

    import app.core.config as cfg

    with pytest.raises(RuntimeError, match="AI_SERVICE_TOKEN"):
        importlib.reload(cfg)


@pytest.mark.parametrize(
    "missing_field",
    ["STORAGE_S3_BUCKET", "STORAGE_S3_ACCESS_KEY", "STORAGE_S3_SECRET_KEY"],
)
def test_missing_storage_s3_config_raises(monkeypatch, missing_field):
    """Config must fail fast if storage bucket/access key/secret key is incomplete."""
    monkeypatch.setenv("STORAGE_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("STORAGE_S3_ACCESS_KEY", "test-access-key")
    monkeypatch.setenv("STORAGE_S3_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv(missing_field, "")

    import app.core.config as cfg

    with pytest.raises(RuntimeError, match="STORAGE_S3"):
        importlib.reload(cfg)


@pytest.mark.parametrize(
    "missing_field",
    ["LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"],
)
def test_missing_langfuse_config_raises_when_enabled(monkeypatch, missing_field):
    """research.md §11: LANGFUSE_ENABLED=true with any connection setting
    blank must fail fast, not silently disable tracing at runtime."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse-web:3000")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv(missing_field, "")

    import app.core.config as cfg

    with pytest.raises(RuntimeError, match=missing_field):
        importlib.reload(cfg)


def test_langfuse_config_optional_when_disabled(monkeypatch):
    """LANGFUSE_ENABLED=false must not require any connection setting."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_HOST", "")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    import app.core.config as cfg

    importlib.reload(cfg)  # must not raise
