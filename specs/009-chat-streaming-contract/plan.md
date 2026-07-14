# Implementation Plan: Chat Streaming Contract Alignment

**Branch**: `009-chat-streaming-contract` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-chat-streaming-contract/spec.md`

## Summary

Align the `/internal/chat` SSE stream with the backend's documented
Conversations contract in three steps: (1) replace the ad-hoc
`{"type": "token", "content": ...}` / `data: [DONE]` envelope with the shared
`{"event": ..., "data": ...}` shape the backend parses; (2) switch from
"run the whole graph, then emit one batched token" to true incremental
token streaming via LangGraph's native `astream(stream_mode="messages")`,
filtered to only the leaf agent's reply; (3) end every stream with a single
terminal `done` event carrying the finalized reply text, a widget slot
(allocation / product / null), and references as `{target_type, target_id}`
over the `{transaction, statement}` vocabulary. The assistant message `id`
is deliberately not emitted — Django assigns it after persistence, once the
stream completes.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI (`StreamingResponse`), LangGraph 1.2.9
(`StateGraph`, `astream(stream_mode="messages")`, `aget_state`),
`langchain-openai` 1.3.4 (`ChatOpenAI`, already streams token chunks under
the messages stream mode), `langchain-core` 1.4.9 (`AIMessageChunk`,
`AnyMessage`, `add_messages`), existing `app.core.audit.record_audit`.

**Storage**: PostgreSQL — own DB only, for the existing LangGraph checkpointer
tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) and
`ai_audit_log`. No backend DB writes (FR-013).

**Testing**: `pytest` + `pytest-asyncio`; mock-first LLM (`USE_MOCK_LLM=1`)
so no real model or network call is made; the chat slice's existing unit
tests assert directly on the SSE text the endpoint emits. The streaming
envelope/leaf-filter unit tests run against a fake checkpointer / mock graph,
consistent with the existing `tests/features/chat/test_chat.py`. The
multi-turn typed-state round-trip (T015) is the one integration concern and
MUST run against real Postgres via the repo's existing Testcontainers `own_pg`
fixture (Constitution Principle I), exercising the real `AsyncPostgresSaver`
serialization of the new `widget` / `message_references` Pydantic models.

**Target Platform**: Linux server (containerized FastAPI service, ASGI).

**Project Type**: Web service (one existing internal SSE endpoint, no frontend).

**Performance Goals**: Time-to-first-token must drop versus the current
batch-then-emit behaviour (the first token event now reaches the proxy while
the reply is still being generated); no explicit numeric SLA is introduced by
this feature.

**Constraints**: The stream MUST filter token events so only the leaf agent's
reply is forwarded — Maestro classification tokens, summary generation, and
planner question-generation must not leak to the proxy (see [research.md](./research.md)).
Mock mode MUST emit the identical event envelope (one token event + one done
event) so backend/frontend development does not branch on `USE_MOCK_LLM`
(FR-011).

**Scale/Scope**: One existing endpoint, one existing feature slice; changes
confined to `app/features/chat/` plus its tests. No new tables, no new
dependencies, no new routes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Mandatory Automated Testing | The new envelope, the terminal `done` payload, the leaf-only token filter, widget emission, and the `{target_type, target_id}` reference shape are all asserted in mock-first unit tests against the SSE text; no live model or network call in CI. Multi-turn routing/continuity is regression-tested in mock mode (FR-012), and the typed `widget`/`message_references` state round-trip through the real `AsyncPostgresSaver` is covered by a Testcontainers-backed integration test (T015). | PASS |
| II. Security & Secrets Discipline | `/internal/chat` already sits behind `require_token`; this feature changes only what is streamed, not the auth surface. No new secrets. | PASS |
| III. Data Protection & Compliance | References carry only a record type and a UUID — never merchant, amount, or other PII. Reply text remains disclaimer-guarded by the existing `with_disclaimer` guard where applicable; the `chat_turn` audit row already captures the turn. No new data leaves the service, and no new field is egressed beyond what the reply already contained. | PASS |
| IV. Data Ownership & Access Boundaries | No backend DB writes are introduced or removed (FR-013). The analysis agent's transaction read stays read-only under `ai_readonly`; this feature changes the streaming presentation only. | PASS |
| V. Feature-Bounded Modular Architecture | All changes live in `app/features/chat/`. Cross-feature access (plan, recommendations) continues to go through the existing service interfaces (`next_question`, `generate_plan`, `match`); no slice reaches into another's internals. | PASS |
| VI. LLM & Agent Architecture | The Maestro orchestrator, the sub-agent delegation, the LangChain/LangGraph runtime, the `ChatOpenAI` access through `get_chat_model()`, and the own-DB checkpointer are all preserved unchanged. Token streaming uses LangGraph's native `stream_mode="messages"` rather than a hand-built tap. Guardrails (disclaimers, grounded citations) are preserved and extended (references now flow to the terminal event). | PASS |
| VII. Operational Readiness | No change to `/health`/`/ready`; no new configuration (the streaming mode is unconditional on the real path). | PASS |
| VIII. Library-First, Minimal Implementation | Incremental streaming is delegated to LangGraph's `astream(stream_mode="messages")` + `ChatOpenAI`'s native token streaming — no hand-rolled generator that polls or re-invokes the model. The event envelope is assembled by a small helper module, not a parallel framework. See [research.md](./research.md) for the rejected hand-built alternative. | PASS |

**Gate status**: All gates pass. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/009-chat-streaming-contract/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/
│   └── chat-stream.md   # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
app/
└── features/
    └── chat/                       # EXISTING slice — modified in place, no new slice
        ├── router.py               # EXISTING — no change (already StreamingResponse)
        ├── schemas/                # NEW PACKAGE — promoted from schemas.py
        │   ├── __init__.py         #   re-exports the public schema surface
        │   ├── request.py          #   ChatTurnRequest (moved from schemas.py, unchanged)
        │   ├── events.py           #   TokenEvent / DoneEvent+DonePayload / ErrorEvent+ErrorPayload
        │   ├── widgets.py          #   AllocationSliderWidget / ProductCardWidget / Widget union + payloads
        │   └── references.py       #   Reference + TargetType (transaction | statement)
        ├── state.py                # MODIFIED — widget: Widget | None; message_references: list[Reference]
        ├── service.py              # REWRITTEN stream path — astream(messages) + aget_state + model_dump_json() framing
        ├── graph.py                # Largely unchanged (entry/edges); leaf nodes named for filtering
        ├── guards.py               # EXISTING — with_disclaimer reused
        ├── summarize.py            # EXISTING — unchanged
        ├── checkpointer.py         # EXISTING — unchanged
        └── agents/
            ├── maestro.py          # EXISTING — unchanged (classification, not streamed)
            ├── analysis.py         # MODIFIED — references -> Reference(target_type="transaction", ...)
            ├── planner.py          # MODIFIED — emit AllocationSliderWidget on plan_complete
            └── recommendation.py   # MODIFIED — emit ProductCardWidget; drop product refs (now in widget)

tests/
└── features/
    └── chat/
        ├── test_chat.py            # MODIFIED — assert new envelope; drop the [DONE] assertion
        ├── test_schemas.py         # NEW — unit tests for the envelope/widget/reference models + serialization
        └── (existing agent tests)  # EXTENDED — assert widget + reference shape per agent
```

**Structure Decision**: No new feature slice. The chat slice already owns the
endpoint being changed (Constitution Principle V), so all edits land inside
`app/features/chat/`. The one structural change is promoting `schemas.py`
into a `schemas/` package (the slice's schema surface grows from one request
model to seven stream models); `__init__.py` re-exports keep every existing
`from app.features.chat.schemas import ...` import working. Because the
envelopes are now Pydantic models, no standalone SSE-helper module is
needed — framing is a one-line `model_dump_json()` in `service.py`
(Principle VIII: no speculative abstraction).

## Complexity Tracking

*No open violations.* No constitution principle is violated or stretched by
this feature; it is a presentation-layer alignment of an existing internal
endpoint to an existing contract, reusing the LangGraph/LangChain streaming
primitives the runtime already provides.
