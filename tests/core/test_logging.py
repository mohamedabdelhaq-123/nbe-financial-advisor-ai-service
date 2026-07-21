"""Unit tests for the structlog pipeline in app.core.logging.

Uses `structlog.testing.capture_logs()` with a fresh, uniquely-named logger
per test so the global cache (`cache_logger_on_first_use=True`) never gets
poisoned for a real, shared logger name used elsewhere in the app.
`capture_logs()` disables all configured processors unless given its own
`processors=` list, so every call here passes `SHARED_PROCESSORS` to exercise
the real pipeline (timestamp/level/logger/redaction) instead of a blank one.
"""

import json
import uuid

from structlog.testing import capture_logs

from app.core.config import settings
from app.core.logging import SHARED_PROCESSORS, get_logger, raw_content_fields


def _fresh_logger():
    return get_logger(f"tests.core.test_logging.{uuid.uuid4().hex}")


def _capture_logs():
    return capture_logs(processors=SHARED_PROCESSORS)


def test_log_entry_has_required_structured_fields():
    logger = _fresh_logger()
    with _capture_logs() as entries:
        logger.info("something_happened", chunk_index=3)

    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == "something_happened"
    assert entry["level"] == "info"
    assert "timestamp" in entry
    assert "logger" in entry
    assert entry["chunk_index"] == 3


def test_exception_logging_includes_type_message_and_stack():
    logger = _fresh_logger()
    with _capture_logs() as entries:
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("unhandled_exception")

    entry = entries[0]
    assert entry["level"] == "error"
    assert "exception" in entry
    serialized = json.dumps(entry["exception"], default=str)
    assert "ValueError" in serialized
    assert "boom" in serialized


def test_redaction_processor_masks_denylisted_fields():
    logger = _fresh_logger()
    with _capture_logs() as entries:
        logger.info(
            "token_issued",
            api_key="sk-real-secret",
            token="abc123",
            password="hunter2",
            authorization="Bearer xyz",
            db_secret="shh",
            some_key="also-shh",
            unrelated_field="fine",
        )

    entry = entries[0]
    assert entry["api_key"] == "[REDACTED]"
    assert entry["token"] == "[REDACTED]"
    assert entry["password"] == "[REDACTED]"
    assert entry["authorization"] == "[REDACTED]"
    assert entry["db_secret"] == "[REDACTED]"
    assert entry["some_key"] == "[REDACTED]"
    assert entry["unrelated_field"] == "fine"


def test_redaction_applies_regardless_of_debug_flag(monkeypatch):
    monkeypatch.setattr(settings, "log_debug_include_raw_content", True)
    logger = _fresh_logger()
    with _capture_logs() as entries:
        logger.debug("debug_call", api_key="still-secret")

    assert entries[0]["api_key"] == "[REDACTED]"


def test_raw_content_fields_empty_by_default():
    assert settings.log_debug_include_raw_content is False
    assert raw_content_fields(prompt="hello", completion="world") == {}


def test_raw_content_fields_included_when_debug_flag_enabled(monkeypatch):
    monkeypatch.setattr(settings, "log_debug_include_raw_content", True)
    assert raw_content_fields(prompt="hello") == {"prompt": "hello"}


def test_raw_content_never_included_at_any_level_when_flag_off():
    """FR-011: the flag gates content, not verbosity — DEBUG severity alone
    must never surface raw content."""
    logger = _fresh_logger()
    with _capture_logs() as entries:
        logger.debug("llm_call", **raw_content_fields(prompt="secret prompt"))

    assert "prompt" not in entries[0]
