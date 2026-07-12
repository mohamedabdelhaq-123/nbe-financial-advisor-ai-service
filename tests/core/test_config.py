"""Fail-fast configuration tests."""

import importlib

import pytest


def test_missing_api_key_raises_when_mock_disabled(monkeypatch):
    """Config must fail fast if USE_MOCK_LLM=false and no real key is set."""
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "__mock__")

    import app.core.config as cfg

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
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
