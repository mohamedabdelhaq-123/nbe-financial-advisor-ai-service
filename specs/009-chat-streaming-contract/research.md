# Research: Chat Streaming Contract Alignment

**Feature**: [spec.md](./spec.md) | **Date**: 2026-07-14

This resolves the design unknowns behind the three-phase change
(envelope + real streaming + widgets/references) before any code is written.
Each decision is grounded in the currently installed stack
(langgraph 1.2.9, langchain-core 1.4.9, langchain-openai 1.3.4) and the
existing `app/features/chat/` implementation.

---

## Decision: Stream tokens via `graph.astream(..., stream_mode="messages")`

**Decision**: Drive incremental token streaming with LangGraph's built-in
`stream_mode="messages"` on the existing compiled graph, not by re-invoking
the model or hand-rolling a polling generator.

**Rationale**: Verified against the installed `langgraph.pregel.Pregel.astream`
signature — `stream_mode` accepts `"messages"`, which yields token-level
`(AIMessageChunk, metadata)` tuples for every `ChatModel` invocation that
occurs *inside* a node. The leaf agents already call
`get_chat_model().ainvoke(...)`; `ChatOpenAI` exposes its tokens through this
same callback path, so enabling real incremental output requires changing the
*driver loop* in `service.py` from `graph.ainvoke(...)` to
`async for chunk in graph.astream(state, config, stream_mode="messages")`, not
rewriting every agent to call `.astream()` itself. This is the textbook
library-first fit (Constitution VIII): the runtime already knows how to tap
chat-model tokens; we only subscribe.

**Alternatives considered**:
- `astream_events(version="v2")` — rejected. It is far noisier
  (`on_chat_model_start`, `on_chat_model_stream`, `on_chain_*`, …), requiring
  more filtering to isolate reply tokens, and is designed for broader event
  observability rather than the narrow "stream the assistant's reply" need
  here. `stream_mode="messages"` yields exactly the chat-model token chunks.
- Switching each agent's `ainvoke` to a manual `astream` and somehow piping
  chunks out of the node — rejected. LangGraph node return values are state
  updates, not async iterators; hand-piping token chunks out of a node would
  require a side-channel (queues/callbacks) that reimplements what
  `stream_mode="messages"` already provides.

---

## Decision: Filter streamed chunks to the leaf agent nodes only

**Decision**: Forward a chunk as a `token` event only when its stream
metadata identifies the emitting node as one of the user-facing leaf agents
(`analysis`, `planner`, `recommendation`, `general`). Maestro's
classification output and the summarize node's summary generation are
consumed internally and must NOT be forwarded.

**Rationale**: The graph invokes a chat model in multiple nodes — `maestro`
(classifies intent to one word), `summarize` (compacts history when it
exceeds 40 messages), and whichever leaf the router selects. Without
filtering, `stream_mode="messages"` would also surface the classifier's
single-word answer and the summary text as token events, leaking internal
plumbing into the user-visible reply. LangGraph's messages-stream metadata
carries the emitting node name (`langgraph_node`), so a single allow-list
filter at the driver keeps only the leaf's tokens. This preserves the current
behaviour where only the final agent's reply is shown, while making it
incremental.

**Alternatives considered**:
- Stream every node's tokens and let the proxy/frontend discard non-leaf
  ones — rejected. The internal contract is "the stream is the assistant's
  reply"; pushing classification noise across the service boundary imposes
  filtering on every consumer and couples them to the graph's internal node
  names.
- Restructure the graph so only one node ever calls the model — rejected as
  needlessly invasive; the classifier and summarizer exist for good reasons
  and the filter is a one-line allow-list.

---

## Decision: Assemble the terminal `done` event from `graph.aget_state()`

**Decision**: After the token stream drains, read the finalized state with
`graph.aget_state(config)` (already used in `service.py` for non-first turns)
and assemble the `done` event from `snapshot.values` — `messages[-1].content`
for the reply text, `message_references` for citations, and the new `widget`
slot.

**Rationale**: `aget_state` returns the canonical, checkpointer-persisted
`StateSnapshot` after the run reaches `END`, so the terminal payload reflects
exactly what was committed for the thread — including the leaf agent's
appended `AIMessage` and any `message_references`/`widget` it returned. This
avoids a fragile "reconstruct the final state from the last streamed chunk"
strategy and reuses a call site the service already makes. The alternative —
`stream_mode=["messages", "values"]` and capturing the last `values` chunk —
duplicates state the checkpointer already holds and is more code for no gain.

**Note**: This couples the terminal event to the checkpointer being present,
which is already a hard precondition of the multi-turn path (the service
short-circuits with an error event when `checkpointer is None`). No new
coupling is introduced.

---

## Decision: Mock mode keeps the graph-less short-circuit, adopts the new envelope

**Decision**: When `settings.use_mock_llm` is set, `service.py` continues to
skip the graph entirely (the existing short-circuit) but emits the *new*
envelope: one `token` event carrying the whole mock reply, followed by one
`done` event with the same content, `widget: null`, and `references: []`.

**Rationale**: The mock nodes today construct `AIMessage` objects directly
rather than calling a `ChatModel`, so `stream_mode="messages"` would yield
nothing for them — true token streaming is a property of real chat-model
invocations, not hand-built message objects. Forcing mock nodes through a
streaming fake model would add machinery purely for shape parity, violating
"no speculative abstraction" (Principle VIII) and the deterministic-mock
requirement (Principle I). Keeping the graph-less short-circuit but unifying
the *envelope* satisfies FR-011 (the proxy sees the same event shapes
regardless of mode) at the cost the spec already accepted: mock replies
arrive as one token rather than many. The real path delivers the genuine
incremental experience.

**Alternatives considered**:
- Route mock mode through the graph too, with a streaming-compatible fake
  model — rejected (machine cost, no user value, harms deterministic tests).
- Drop the mock short-circuit and run the real path with a mock model —
  rejected; the existing mock short-circuit also bypasses state resumption,
  and widening mock's scope is out of this feature's purview (FR-012 only
  requires continuity not to *regress*, which holds because the real path is
  unchanged in its state handling).

---

## Decision: Widget slot on `ConversationState`; typed payloads per leaf agent

**Decision**: Add a `widget: dict | None` field to `ConversationState`
(default `None`). Each leaf agent populates it:
`planner` sets `{"type": "allocation_slider", "payload": {"allocations":
[{"category", "percentage"}, ...]}}` only on `plan_complete` (null while
asking questions); `recommendation` sets `{"type": "product_card",
"payload": {"products": [{"product_id", "product_name", "similarity"}, ...]}}`;
`analysis` and `general` leave it `None`. The terminal `done` event always
includes the slot (populated or null).

**Rationale**: The widget is conceptually part of the reply the agent
produces, so it belongs in the state the agent returns — not assembled after
the fact by the driver from a second source. Carrying it in state also means
the checkpointer persists it per thread, so a re-read of the conversation
yields the same widget. Keeping the slot always-present on the terminal event
(empty when no agent set it) gives the frontend one consistent shape
(FR-005). The payload shapes mirror what the agents already compute
(`BudgetAllocation.category`/`percentage`; the `ProductMatch` fields the
recommendation agent already stringifies), so no new computation is
introduced.

**Alternatives considered**:
- Emit widgets as a separate SSE event type (`{"event": "widget", ...}`)
  alongside `done` — rejected. The backend contract specifies a single
  terminal `done` carrying `widget` and `references` together; splitting
  them would diverge from that contract.
- Untyped `dict` widgets emitted as-is into the SSE JSON — superseded (see
  the "Typed stream schemas" decision below). The stream envelope, widgets,
  and references are now first-class Pydantic models so producers are
  validated at construction and the wire shape is enforced by the schema,
  not by convention.

---

## Decision: Typed stream schemas live in a `schemas` package

**Decision**: Promote `app/features/chat/schemas.py` from a single file to a
`app/features/chat/schemas/` package. The request DTO (`ChatTurnRequest`)
moves into `request.py`; the new stream contract — `TokenEvent` / `DoneEvent`
/ `ErrorEvent` envelopes, the `Widget` discriminated union
(`allocation_slider` / `product_card`), and `Reference`
(`{target_type, target_id}`) — each get their own module
(`events.py`, `widgets.py`, `references.py`). `__init__.py` re-exports the
public surface so existing `from app.features.chat.schemas import ...`
imports keep working unchanged.

**Rationale**: The chat slice's schema surface grows substantially with this
feature (one request model → six stream models). A package keeps each
concern in its own navigable file and gives the wire contract a single,
importable, validated definition rather than ad-hoc dicts assembled in the
service. Because the envelopes are now models, SSE framing collapses to
`f"data: {event.model_dump_json()}\n\n"` — the previously-planned standalone
`events.py` helper module is deleted from the plan; its job is one line of
presentation in `service.py`, not a separate abstraction (Principle VIII).
The package also retires the previously-deferred "typed widget models" idea
— they are now built, not deferred.

**ConversationState typing**: `widget` is typed as `Widget | None` and
`message_references` as `list[Reference]` on the TypedDict, so agents
construct validated objects and the terminal-event assembly is a
`.model_dump_json()` away. The `AsyncPostgresSaver` checkpointer serializes
Pydantic v2 models (its `JsonPlusSerializer` supports them), so multi-turn
persistence round-trips the typed values; a regression test
(`test_chat.py`, non-first-turn with a widget) locks this in. If a
serialization edge case surfaced, the fallback would be `model_dump()` dicts
in state reconstructed at the boundary — but typed-in-state is the default.

**Alternatives considered**:
- Keep `schemas.py` as one growing file — rejected; the file would hold seven
  unrelated models spanning request, SSE, widgets, and references, which is
  exactly the per-file layering-by-shape the slice convention avoids at the
  directory level.
- A new top-level `app/features/chat/stream_schemas.py` alongside
  `schemas.py` — rejected; two sibling schema files in one slice is messier
  than one package, and the package keeps the single `schemas` import path
  every caller already uses.

---

## Decision: References become `{target_type, target_id}` over `{transaction, statement}`

**Decision**: Migrate `message_references` from its current `{table, id}`
shape to `{target_type, target_id}`, where `target_type ∈ {"transaction",
"statement"}`. The analysis agent emits one `transaction` reference per cited
transaction. The recommendation agent no longer emits `product` references —
its matches move into the `product_card` widget payload. No agent currently
emits a `statement` reference, but the vocabulary is left open for it so a
future agent that grounds in a statement needs no contract change.

**Rationale**: Matches the backend's Conversations contract exactly
(`{target_type, target_id}`) and the user's explicit scoping (references are
either a transaction or a statement). Moving product matches into the widget
removes a vocabulary mismatch — `products` are not in the reference target
set the contract defines, and duplicating them as both a widget and a
reference would be redundant. Keeping `statement` in the allowed vocabulary
even though no agent produces it yet keeps the wire format stable when one
does. References carry only a UUID (Principle III) — never merchant/amount.

**Alternatives considered**:
- A central `{table, id} → {target_type, target_id}` mapper in the driver —
  rejected. The user asked for the native shape, and changing the four agents
  to emit the contract shape directly is small and removes a translation
  layer (Principle VIII).
- Keeping `products` as a reference type — rejected; out of the agreed
  vocabulary.

---

## Decision: The assistant message `id` is never emitted by this service

**Decision**: The terminal `done` event contains `content`, `widget`, and
`references` only. No `id` field is produced.

**Rationale**: The user's explicit decision — Django assigns the persisted
message identifier after the stream completes, when it persists the
finalized reply. Emitting an AI-service-side id would create a second source
of truth for message identity and force the backend to reconcile or
overwrite it. Omitting it keeps the internal contract narrower and matches
"internal Django↔AI-service calls follow their own, simpler internal
contract" (API Design Guidelines §1).

---

## Decision: SSE framing stays manual inside `StreamingResponse`

**Decision**: Keep the existing `StreamingResponse(..., media_type=
"text/event-stream")` in `router.py` and emit each event as a literal
`data: {json}\n\n` line from `service.py` (via the new `events.py` helpers).

**Rationale**: The endpoint already works this way; the only error in the
current output is the *content* of each frame (wrong field names, missing
`done`), not the framing. Introducing an SSE helper library or FastAPI
SSE plugin would be speculative machinery (Principle VIII) for a format that
is four bytes of framing per event. Manual framing also keeps the stream
fully under the service's control for the error path (FR-010 emits one
`error` event and closes).

**Alternatives considered**:
- `sse-starlette` — rejected; adds a dependency for behaviour achievable in
  one `yield f"data: {payload}\n\n"`.
