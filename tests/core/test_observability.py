"""Unit tests for app.core.observability: `configure()`'s no-crash behavior
and the redaction span processor's attribute-stripping.

Entirely in-process — no test starts a real Langfuse/ClickHouse container or
makes a real OTLP network call (Constitution Principle I; research.md §5).
The auto-instrumentation coverage test drives a real LangChain call path
(`langchain_core`'s own `FakeListChatModel`) rather than a real provider, to
stay mock-first while still proving `LangChainInstrumentor` actually wraps
the same call shape `app/core/llm.py` uses.
"""

import pytest
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from app.core import observability
from app.core.request_logging import current_feature


@pytest.fixture(autouse=True)
def _reset_instrumentation():
    """`LangChainInstrumentor` is a process-wide singleton (`BaseInstrumentor.__new__`
    always returns the same instance), so one test's `instrument()` call would
    otherwise leak into the next. Uninstrument before and after every test."""
    instrumentor = LangChainInstrumentor()
    if instrumentor._is_instrumented_by_opentelemetry:
        instrumentor.uninstrument()
    observability._tracer_provider = None
    yield
    if instrumentor._is_instrumented_by_opentelemetry:
        instrumentor.uninstrument()
    observability._tracer_provider = None


def _disable_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observability.settings.langfuse, "enabled", False)


def _set_dummy_langfuse_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observability.settings.langfuse, "enabled", True)
    monkeypatch.setattr(observability.settings.langfuse, "host", "http://localhost:3000")
    monkeypatch.setattr(observability.settings.langfuse, "public_key", "pk-test")
    monkeypatch.setattr(observability.settings.langfuse, "secret_key", SecretStr("sk-test"))


class TestConfigureNoCrashBehavior:
    def test_noop_when_langfuse_disabled(self, monkeypatch):
        _disable_langfuse(monkeypatch)

        observability.configure()

        assert observability._tracer_provider is None
        assert not LangChainInstrumentor()._is_instrumented_by_opentelemetry

    @pytest.mark.parametrize("missing_field", ["host", "public_key", "secret_key"])
    def test_noop_when_enabled_but_any_single_connection_setting_absent(
        self, monkeypatch, missing_field
    ):
        """Contract: enabled-but-partially-configured is a fully supported
        "tracing off" state, not a startup failure (contracts/
        observability-config.md §1) — logs a warning instead."""
        _set_dummy_langfuse_settings(monkeypatch)
        # Blank the targeted field using the right type (str vs SecretStr).
        monkeypatch.setattr(
            observability.settings.langfuse,
            missing_field,
            SecretStr("") if missing_field == "secret_key" else "",
        )

        observability.configure()

        assert observability._tracer_provider is None
        assert not LangChainInstrumentor()._is_instrumented_by_opentelemetry

    def test_attempts_instrumentation_without_raising_when_all_settings_present(self, monkeypatch):
        """Points at a dummy/local endpoint — nothing needs to be listening
        there; setup must not raise even though export will later fail."""
        _set_dummy_langfuse_settings(monkeypatch)

        observability.configure()  # must not raise

        assert observability._tracer_provider is not None
        assert LangChainInstrumentor()._is_instrumented_by_opentelemetry

    def test_swallows_setup_failures_instead_of_raising(self, monkeypatch):
        """FR-005: a broken exporter/instrumentor must never surface as a
        startup failure."""
        _set_dummy_langfuse_settings(monkeypatch)

        def _boom(**_kwargs):
            raise RuntimeError("simulated exporter construction failure")

        monkeypatch.setattr(observability, "OTLPSpanExporter", _boom)

        observability.configure()  # must not raise

        assert observability._tracer_provider is None


class TestRedactionSpanProcessor:
    """Constructs real in-memory spans (via a throwaway TracerProvider feeding
    an InMemorySpanExporter) and asserts on what the processor lets through."""

    @staticmethod
    def _process(attributes: dict[str, object]) -> dict[str, object]:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(observability.RedactionSpanProcessor())
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("llm-call") as span:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        finished = exporter.get_finished_spans()
        assert len(finished) == 1
        return dict(finished[0].attributes or {})

    def test_masks_card_number(self):
        result = self._process({"input.value": "my card is 1234567812345678, ship it"})
        assert "1234567812345678" not in result["input.value"]
        assert "[CARD]" in result["input.value"]

    def test_masks_email(self):
        result = self._process({"input.value": "reach me at jane.doe@example.com thanks"})
        assert "jane.doe@example.com" not in result["input.value"]
        assert "[EMAIL]" in result["input.value"]

    def test_masks_phone(self):
        result = self._process({"input.value": "call me on 5551234567890 today"})
        assert "5551234567890" not in result["input.value"]
        assert "[PHONE]" in result["input.value"]

    def test_leaves_unrelated_attributes_untouched(self):
        result = self._process(
            {
                "input.value": "card 1234567812345678",
                "llm.model_name": "gpt-4o-mini",
                "openinference.span.kind": "LLM",
            }
        )
        assert result["llm.model_name"] == "gpt-4o-mini"
        assert result["openinference.span.kind"] == "LLM"
        assert "[CARD]" in result["input.value"]

    def test_non_string_attributes_pass_through_unmodified(self):
        result = self._process({"llm.token_count.total": 42})
        assert result["llm.token_count.total"] == 42

    def test_stamps_current_feature_onto_spans_processed_during_a_request(self):
        token = current_feature.set("chat")
        try:
            result = self._process({"llm.model_name": "gpt-4o-mini"})
        finally:
            current_feature.reset(token)

        assert result["langfuse.trace.metadata.feature"] == "chat"

    def test_stamps_nothing_outside_any_request_context(self):
        assert current_feature.get() is None  # no request in flight in this test

        result = self._process({"llm.model_name": "gpt-4o-mini"})

        assert "langfuse.trace.metadata.feature" not in result


class TestConfigureCapturesLangChainCalls:
    def test_span_captured_for_fake_chat_model_invocation(self, monkeypatch):
        """Validates auto-instrumentation actually wraps LangChain calls with
        zero LLM-call-site changes — the same call shape app/core/llm.py's
        get_chat_model() produces, just backed by a fake model here to stay
        mock-first (Constitution Principle I)."""
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        captured = InMemorySpanExporter()
        monkeypatch.setattr(observability, "OTLPSpanExporter", lambda **_kwargs: captured)
        _set_dummy_langfuse_settings(monkeypatch)

        observability.configure()
        assert observability._tracer_provider is not None

        model = FakeListChatModel(responses=["hello"])
        model.invoke("hi there")

        observability._tracer_provider.force_flush()
        spans = captured.get_finished_spans()

        assert len(spans) >= 1
        attributes = dict(spans[0].attributes)
        assert attributes.get("openinference.span.kind") == "LLM"
