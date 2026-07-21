# Phase 1 Data Model: LLM Observability with Langfuse

## Summary

This feature adds **no tables, models, or migrations to the AI service's own database**. It introduces one new configuration surface (owned by this service) and observes three conceptual entities that live entirely inside Langfuse's own storage, which this service never queries, writes to, or represents as ORM models.

## Owned: Observability configuration

Lives in `app/core/config.py`'s existing `Settings` class, following the same shape as `embedding_*`/`storage_s3_*` fields — plain settings, not a persisted entity.

| Field | Type | Default | Notes |
|---|---|---|---|
| `langfuse_host` | `str` | `""` | Base URL of the self-hosted Langfuse instance (e.g. `http://langfuse-web:3000` inside the compose network). Empty ⇒ tracing disabled. |
| `langfuse_public_key` | `str` | `""` | Project public key, generated in the Langfuse UI after first login (see quickstart.md). |
| `langfuse_secret_key` | `str` | `""` | Project secret key, paired with the above for OTLP Basic Auth. Never committed — supplied via `.env`, same handling as `openai_api_key`. |

Validation rule: `configure()` treats "any of the three empty" as "tracing disabled" and skips instrumentation entirely (no partial/invalid state possible — either all three are present or tracing is off).

## External (Langfuse-owned, not modeled here)

These are the domain concepts named in the feature spec's Key Entities section. They are documented here for traceability back to the spec, not because this service implements or persists them — they exist solely inside Langfuse's Postgres/ClickHouse and are viewed through the Langfuse UI.

- **Trace**: One logical operation (a chat turn, a normalization run). Has a start/end time, overall status, and — via OpenInference span attributes — an association back to the originating feature/flow. Corresponds to spec User Story 1 & 2.
- **Observation (span)**: A single step within a trace — an LLM call, a LangGraph node, a tool invocation. Carries input/output (subject to the redaction rules in research.md §3), timing, model identity, token usage where the underlying call reports it, and an originating-feature attribute (research.md §7) derived from the request path, not hand-set per call site.
- **Usage metric**: Aggregated token/request counts, computed by Langfuse itself from stored observations, sliceable by time range and (via span attributes) by originating feature. Corresponds to spec User Story 2.

No state transitions apply — these are append-only observability records managed entirely by Langfuse's own ingestion pipeline.
