"""LLM call tracing — OpenTelemetry auto-instrumentation exported to Langfuse.

`configure()` is called once at startup (app/main.py), immediately after
app_logging.configure(). It wires a process-wide `TracerProvider` that:

  - auto-instruments every LangChain/LangGraph call site via
    `LangChainInstrumentor().instrument()` — zero changes to app/core/llm.py
    or any feature's call site (research.md §2);
  - pattern-redacts card/email/phone-shaped attribute values on every span
    before it reaches the exporter — Constitution Principle III gives this
    export path zero exception, unlike the live LLM inference call itself
    (research.md §3);
  - exports via OTLP/HTTP to Langfuse's ingestion endpoint, batched off the
    request path (`BatchSpanProcessor`).

`LANGFUSE_ENABLED=false` ⇒ tracing disabled; `configure()` returns before
touching any of the above (research.md §6, §10). `LANGFUSE_ENABLED=true`
with host/key missing fails fast at startup instead, in `app/core/config.py`
— never reaches this module (research.md §10/§11). Any *setup* failure once
config is valid (bad host, unreachable endpoint, etc.) is caught and logged,
never raised — an unreachable/misconfigured Langfuse must never block
startup or a user-facing request (FR-005, research.md §4).
"""

import base64
import re

from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.attributes import BoundedAttributes
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanProcessor

from app.core.config import settings
from app.core.logging import get_logger
from app.core.request_logging import current_feature

# Langfuse-recognized OTel attribute for arbitrary per-trace metadata
# (langfuse.com/integrations/native/opentelemetry) — stamped onto every span
# processed during a request, not just the root span, since Langfuse's own
# docs note filtering/aggregation increasingly operate per-observation, not
# just per-trace (research.md §7).
_FEATURE_ATTRIBUTE = "langfuse.trace.metadata.feature"

logger = get_logger(__name__)

# Set by a successful configure() call; stays None while tracing is disabled
# or setup failed. Not part of the public contract (configure() itself stays
# a same-shape, no-return sibling of app.core.logging.configure()) — exists
# so the provider can be flushed/shut down (tests; a future app shutdown
# hook) without configure() needing to expose it as a return value.
_tracer_provider: TracerProvider | None = None

# Mirrors the regex shapes in app/features/chat/guards.py::strip_pii() as a
# starting pattern set — not imported directly, since that function is
# feature-slice code and Principle V forbids a cross-cutting core module
# reaching into a feature slice (research.md §3).
_CARD_PATTERN = re.compile(r"\b\d{16}\b")
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE_PATTERN = re.compile(r"\b\d{10,}\b")


def _redact(value: str) -> str:
    value = _CARD_PATTERN.sub("[CARD]", value)
    value = _EMAIL_PATTERN.sub("[EMAIL]", value)
    value = _PHONE_PATTERN.sub("[PHONE]", value)
    return value


class RedactionSpanProcessor(SpanProcessor):
    """Masks card/email/phone-shaped values in span attributes before export,
    and stamps the originating feature/flow onto every span for Langfuse's
    usage dashboard.

    Every span passes through the redaction step unconditionally — Principle
    III gives this feature's telemetry export zero exception, unlike the
    live LLM inference call it observes (research.md §3). Whole-attribute
    hiding (OpenInference's `OPENINFERENCE_HIDE_*`) was rejected as the
    mechanism: it would satisfy compliance by deleting the trace's
    usefulness, which conflicts with FR-001's "inputs and outputs visible"
    requirement.

    Feature attribution (US2, FR-006, SC-005, research.md §7) reads the
    `current_feature` `ContextVar` `app.core.request_logging` binds per
    request and stamps it as `langfuse.trace.metadata.feature` on every span
    processed while that request is in flight — no per-call-site wiring.
    Spans processed outside any request context (`current_feature` unset)
    are left unstamped rather than given a placeholder value.

    Mutates `span._attributes` (the SDK's internal `BoundedAttributes`) via
    its backing dict rather than `__setitem__`: by the time `on_end()` fires,
    `Span.end()` has already flipped `_immutable = True` on it (see
    `opentelemetry.sdk.trace.Span.end()`), so the normal write path raises.
    There's no public, mutation-safe API for rewriting a span's attributes
    post-hoc — the SDK expects processors to observe, not rewrite — so this
    reaches into a private field deliberately; it's the one hand-rolled piece
    Principle VIII's library-first rule explicitly carves an exception for
    here (research.md §3; plan.md Constitution Check row VIII).
    """

    def on_end(self, span: ReadableSpan) -> None:
        attributes = span._attributes  # noqa
        if not isinstance(attributes, BoundedAttributes):
            return
        for key, value in list(attributes.items()):
            if isinstance(value, str):
                redacted = _redact(value)
                if redacted != value:
                    attributes._dict[key] = redacted  # noqa
            elif isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
                # E.g. OpenInference's `tag.tags` (langchain run tags), set as a
                # real List[str] attribute rather than flattened indexed keys —
                # Principle III's redaction is unconditional across all attributes.
                redacted_seq = tuple(_redact(v) for v in value)
                if redacted_seq != tuple(value):
                    attributes._dict[key] = redacted_seq  # noqa

        feature = current_feature.get()
        if feature is not None:
            attributes._dict[_FEATURE_ATTRIBUTE] = feature  # noqa


def configure() -> None:
    """Wire process-wide LLM call tracing, exported to Langfuse.

    No-op when `langfuse_enabled` is False — the explicit on/off switch,
    independent of whether host/key are set (research.md §10). `app/core/
    config.py` already fails fast at startup if `langfuse_enabled` is True
    with any of host/public key/secret key empty, so that combination should
    never reach this function in practice; the same check is repeated here
    (no-op + warning, not a raise) purely as defense-in-depth, since this
    function's own contract is that it must never raise regardless. Any setup
    failure (bad host, unreachable endpoint, etc.) is logged and swallowed so
    a misconfigured or down Langfuse can never block startup (FR-005,
    research.md §4).
    """
    global _tracer_provider
    if _tracer_provider is not None:
        return
    if not settings.langfuse_enabled:
        return
    if not (
        settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key
    ):
        logger.warning("observability_enabled_but_missing_connection_settings")
        return

    try:
        # Headers are passed directly to the exporter's constructor rather
        # than via the OTEL_EXPORTER_OTLP_HEADERS env var: the installed
        # opentelemetry-exporter-otlp-proto-http's env-var header parser only
        # URL-decodes a value when it matches its *strict* grammar, which a
        # literal space after "Basic" already fails — it falls back to a
        # "liberal" parser that does NOT decode, so percent-encoding the
        # base64 padding here would corrupt the header instead of protecting
        # it (verified against the pinned opentelemetry-sdk version).
        # Passing headers as a dict sidesteps that parsing path entirely.
        credentials = base64.b64encode(
            f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
        ).decode()
        exporter = OTLPSpanExporter(
            endpoint=f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
            headers={"Authorization": f"Basic {credentials}"},
        )
        provider = TracerProvider()
        # Redaction chained first so the BatchSpanProcessor below only ever
        # hands the exporter already-masked attribute values (research.md §3).
        provider.add_span_processor(RedactionSpanProcessor())
        provider.add_span_processor(BatchSpanProcessor(exporter))
        LangChainInstrumentor().instrument(tracer_provider=provider)
        _tracer_provider = provider
    except Exception:
        logger.exception("observability_configure_failed")
