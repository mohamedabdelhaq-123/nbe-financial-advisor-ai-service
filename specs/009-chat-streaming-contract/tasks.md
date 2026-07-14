# Tasks: Chat Streaming Contract Alignment

**Input**: Design documents from `/specs/009-chat-streaming-contract/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/chat-stream.md, quickstart.md

**Tests**: Included — Constitution Principle I (Mandatory Automated Testing) requires every feature to ship with mock-first automated tests, so test tasks are mandatory here regardless of the template's optional default.

**Organization**: Tasks are grouped by user story. US1 (the streamed incremental reply + terminal `done` event) is the MVP; US2 (widgets) and US3 (references) build on its terminal-event assembly but are independently testable via agent-level unit tests.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single-project FastAPI service. App code under `app/features/chat/`; tests under `tests/features/chat/`.
- All paths are repository-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Promote the chat slice's schema surface from a single file to a package, so the new stream models have a home. No behaviour change — existing imports must keep resolving.

- [X] T001 Promote `app/features/chat/schemas.py` to a package: create `app/features/chat/schemas/__init__.py` and `app/features/chat/schemas/request.py`; move `ChatTurnRequest` (and its `ConfigDict`/`Field` imports) verbatim from `schemas.py` into `request.py`; delete the old `schemas.py`; have `__init__.py` re-export `ChatTurnRequest` so `from app.features.chat.schemas import ChatTurnRequest` (used in `router.py` and `service.py`) still resolves. **Acceptance**: `uv run pytest -q` passes (no import regressions) and `uv run ruff check app/features/chat && uv run mypy app/features/chat` is clean.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The Pydantic models that define the new wire contract, plus the typed `ConversationState` fields. Every user story reads or writes these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] Create `app/features/chat/schemas/references.py`: `TargetType = Literal["transaction", "statement"]` and `class Reference(BaseModel)` with `target_type: TargetType` and `target_id: str` (UUID only). Per [data-model.md](./data-model.md) §Reference and FR-006.
- [X] T003 [P] Create `app/features/chat/schemas/widgets.py`: `Allocation(BaseModel)` (`category: str`, `percentage: float` with `ge=0, le=100`); `AllocationSliderPayload(BaseModel)` (`allocations: list[Allocation]`); `ProductMatchPayloadItem(BaseModel)` (`product_id: str`, `product_name: str`, `similarity: float` with `ge=0.0, le=1.0`); `ProductCardPayload(BaseModel)` (`products: list[ProductMatchPayloadItem]`); `AllocationSliderWidget(BaseModel)` (`type: Literal["allocation_slider"] = "allocation_slider"`, `payload: AllocationSliderPayload`); `ProductCardWidget(BaseModel)` (`type: Literal["product_card"] = "product_card"`, `payload: ProductCardPayload`); `Widget = AllocationSliderWidget | ProductCardWidget`. Per [data-model.md](./data-model.md) §Widget.
- [X] T004 Create `app/features/chat/schemas/events.py`: `class TokenEvent(BaseModel)` (`event: Literal["token"] = "token"`, `data: str`); `class DonePayload(BaseModel)` (`content: str`, `widget: Widget | None = None`, `references: list[Reference] = Field(default_factory=list)` — **no `id` field**, FR-003); `class DoneEvent(BaseModel)` (`event: Literal["done"] = "done"`, `data: DonePayload`); `class ErrorPayload(BaseModel)` (`message: str`); `class ErrorEvent(BaseModel)` (`event: Literal["error"] = "error"`, `data: ErrorPayload`). Imports `Reference` from `schemas.references` and `Widget` from `schemas.widgets`. (Depends on T002, T003.)
- [X] T005 Update `app/features/chat/schemas/__init__.py` to re-export the new public surface (`Reference`, `TargetType`, `Widget`, `AllocationSliderWidget`, `ProductCardWidget`, `TokenEvent`, `DoneEvent`, `DonePayload`, `ErrorEvent`, `ErrorPayload`) alongside `ChatTurnRequest`. (Depends on T002–T004.)
- [X] T006 [P] Create `tests/features/chat/test_schemas.py`: assert `TokenEvent(data="x").model_dump_json()` == `{"event":"token","data":"x"}`; assert a `DoneEvent` serializes with `widget` and `references` keys present and **no** `id` key anywhere (FR-003, FR-005, FR-008); assert `Reference(target_type="products", ...)` is rejected by the Literal (FR-006); assert the `Widget` union accepts both widget types and rejects an unknown `type`. (Depends on T002–T005.)
- [X] T007 Update `app/features/chat/state.py`: change `message_references` from `list[dict]` to `list[Reference]` and add `widget: Widget | None` to `ConversationState` (import the types from `app.features.chat.schemas`). (Depends on T002, T003.)

**Checkpoint**: Package + models + typed state ready. User story implementation can now begin.

---

## Phase 3: User Story 1 — Streamed incremental reply + terminal `done` event (Priority: P1) 🎯 MVP

**Goal**: `/internal/chat` emits the assistant's reply as incremental `token` events (filtered to the leaf agent only) and concludes with exactly one terminal `done` event carrying the finalized reply, using the shared `{event, data}` envelope. Replaces the ad-hoc `{"type":...}` / `data: [DONE]` output.

**Independent Test**: Send one chat turn (mock mode) and verify the SSE body contains `{"event":"token","data":...}` frames and exactly one `{"event":"done","data":{...}}`, with no `data: [DONE]` and no `{"type":...}` frame. Then, with an injected streaming fake model, verify >1 token event before `done` and that non-leaf node tokens are not forwarded.

### Implementation for User Story 1

- [X] T008 [US1] In `app/features/chat/service.py`, replace the `graph.ainvoke(...)` driver with `async for chunk in graph.astream(state, config, stream_mode="messages")`; each chunk is `(AIMessageChunk, metadata)` — forward a token event ONLY when `metadata.get("langgraph_node")` is in `{analysis, planner, recommendation, general}` and `chunk.content` is non-empty; emit each as `f"data: {TokenEvent(data=chunk.content).model_dump_json()}\n\n"`. (Leaf-only filter per [research.md](./research.md); FR-001, FR-004.)
- [X] T009 [US1] In `app/features/chat/service.py`, after the stream drains, read `snapshot = await graph.aget_state(config)` and emit exactly one terminal event: `DonePayload(content=<last AI message content, "" if absent>, widget=snapshot.values.get("widget"), references=list(snapshot.values.get("message_references") or []))`, framed as `f"data: {DoneEvent(data=...).model_dump_json()}\n\n"`. Guarantees FR-002, FR-005, FR-008; the slot is always present even when null/empty. (Depends on T007, T008.)
- [X] T010 [US1] In `app/features/chat/service.py`, wrap the graph run in `try/except Exception` and on failure emit exactly one `f"data: {ErrorEvent(data=ErrorPayload(message=str(exc))).model_dump_json()}\n\n"` then end the stream (no `done` follows an `error`); keep the existing "checkpointer is None" short-circuit but switch its payload to `ErrorEvent` (FR-010).
- [X] T010a [US1] In `app/features/chat/service.py`, handle a mid-stream client disconnect: detect cancellation of the `astream` loop (e.g. `asyncio.CancelledError`, or `Request.is_disconnected()` polled between token yields) and stop producing immediately — emit no partial `done`, avoid any double audit write, and leave checkpointer state consistent for the next turn (spec Edge Case: client disconnect). **Acceptance**: the disconnect case in T014a passes (same `service.py` file — strictly sequential after T010).
- [X] T011 [US1] In `app/features/chat/service.py`, rewrite the `settings.use_mock_llm` short-circuit to emit the new envelope: one `TokenEvent` carrying the whole mock reply, then one `DoneEvent` with the same `content`, `widget=None`, `references=[]` (FR-011 — same envelope as the real path, single batch).
- [X] T012 [US1] In `app/features/chat/service.py`, keep the `chat_turn` audit write (action/detail unchanged) after the stream ends, wrapped in its existing best-effort `try/except` (no behaviour change; FR-013 — no new writes).

### Tests for User Story 1

- [X] T013 [P] [US1] Update `tests/features/chat/test_chat.py`: replace the `"[DONE]" in body` assertion with assertions that the body contains `{"event":"token","data":` and exactly one `{"event":"done","data":`; assert `done.data` has `widget` and `references` keys and **no** `id`; assert no `data: [DONE]` and no `{"type":` anywhere; keep the 401/200/content-type assertions (FR-001, FR-002, FR-004, FR-009, FR-011).
- [X] T014 [P] [US1] Add a real-path streaming test in a **new** `tests/features/chat/test_streaming.py` (kept separate from `test_chat.py` so it can run parallel to T013): monkeypatch `app.core.llm.get_chat_model` to return a fake `ChatOpenAI`-shaped model whose `.ainvoke` is consumed via the messages stream (or monkeypatch `get_chat_model` to a real `ChatOpenAI` pointed at a deterministic in-process stub that yields multiple chunks); assert **more than one** `token` event precedes `done`, and assert no `token` event's content equals the Maestro classification word (proves the leaf-only filter). (FR-001, SC-002.)
- [X] T014a [US1] Add streaming-edge tests in `tests/features/chat/test_streaming.py` (after T014, same file — sequential): (a) **error event** — force a mid-graph failure and assert exactly one `{"event":"error","data":{"message":...}}` frame and no `done` frame follows (FR-010); (b) **empty content** — a reply whose content is empty still emits exactly one `done` with `content == ""` and the `widget`/`references` slots present (spec Edge Case: empty content); (c) **widget + references combo** — a state carrying both a populated `widget` and non-empty `references` yields a single `done` carrying both populated (spec Edge Case: plan grounded in transactions); (d) **client disconnect** — simulate disconnect mid-stream and assert production stops with no trailing `done` and no exception escaping the endpoint (verifies T010a).
- [X] T015 [US1] Add a multi-turn continuity **integration** test backed by the repo's Testcontainers `own_pg` fixture (Constitution Principle I): build the graph with a real Postgres `AsyncPostgresSaver` checkpointer, run a first turn that leaves `stage="planning"`, `questions_asked>0`, `planner_answers`, and a populated `widget`/`message_references`, then drive a non-first turn and assert it still routes through the new streaming path with the answer captured (FR-012). Critically, assert the typed `widget`/`message_references` Pydantic values survive the real-checkpointer serialization round-trip on the second turn (routing is also covered mock-first in `test_chat.py`; this test is the real-Postgres integration layer).

**Checkpoint**: US1 fully functional — the stream uses the new envelope and real incremental tokens, ending in one structured `done`. This is the shippable MVP.

---

## Phase 4: User Story 2 — Widgets travel with the finalized reply (Priority: P2)

**Goal**: Leaf agents populate the `widget` slot so the terminal `done` event carries an `allocation_slider` for completed plans and a `product_card` for recommendations (null otherwise).

**Independent Test**: Call each leaf agent directly (via the existing agent-level tests) and assert the `widget` it returns matches the contract; the terminal-event integration is already covered by US1's `DonePayload` reading `widget` from state.

### Implementation for User Story 2

- [X] T016 [P] [US2] In `app/features/chat/agents/planner.py`, when the plan completes (`generate_plan` returns allocations), build `AllocationSliderWidget(payload=AllocationSliderPayload(allocations=[Allocation(category=a.category, percentage=a.percentage) for a in allocations]))` and include `widget=<that>` in the returned state-update dict alongside the existing `messages`/`stage="plan_complete"`; while still asking questions, do not set `widget` (it stays `None`). (FR-005.)
- [X] T017 [P] [US2] In `app/features/chat/agents/recommendation.py`, build `ProductCardWidget(payload=ProductCardPayload(products=[ProductMatchPayloadItem(product_id=str(m.product_id), product_name=m.product_name, similarity=m.similarity) for m in product_matches]))` and include `widget=<that>` in the return; **remove** the old product `message_references` (products now live in the widget payload, per [research.md](./research.md)). Set `message_references=[]`. (FR-005.)
- [X] T018 [P] [US2] Verify `_general_node` in `app/features/chat/graph.py` and the `analysis` agent rely on the `widget` default (`None`) — no change needed unless `widget` is absent from their return; if so, leave it unset so `DonePayload.widget` resolves to `None` for general/analysis replies (FR-005).

### Tests for User Story 2

- [X] T019 [P] [US2] Extend `tests/features/chat/test_planner_integration.py`: assert a `plan_complete` return carries `widget` of type `allocation_slider` whose `allocations` sum to 100; assert a still-asking return has `widget is None`.
- [X] T020 [P] [US2] Extend `tests/features/chat/test_recommendation_integration.py`: assert the return carries `widget` of type `product_card` whose `products` mirror the matched products, and that `message_references == []`.

**Checkpoint**: US1 + US2 both work — rich replies carry widgets through the same stream.

---

## Phase 5: User Story 3 — Replies cite underlying financial records (Priority: P3)

**Goal**: Grounded replies carry `{target_type, target_id}` references over the `{transaction, statement}` vocabulary.

**Independent Test**: Run the analysis agent against fixture transactions and assert each cited record appears as `Reference(target_type="transaction", target_id=<uuid>)`; assert no other `target_type` is ever produced.

### Implementation for User Story 3

- [X] T021 [P] [US3] In `app/features/chat/agents/analysis.py`, replace the `{"table": "transactions", "id": getattr(txn, "id", None)}` dict with `Reference(target_type="transaction", target_id=str(txn.id))` for each cited transaction (FR-006, FR-007). Import `Reference` from `app.features.chat.schemas`.

### Tests for User Story 3

- [X] T022 [P] [US3] Extend `tests/features/chat/test_analysis_agent.py`: assert every entry in the returned `message_references` is a `Reference` with `target_type == "transaction"` and a stringified-UUID `target_id`; assert the count matches the cited transactions; assert no `target_type` outside `{transaction, statement}` appears (FR-006, FR-007, SC-004).
- [X] T023 [US3] Add a vocabulary-openness assertion in `tests/features/chat/test_schemas.py`: `Reference(target_type="statement", target_id=<uuid>)` validates (so a future statement-grounded agent needs no contract change), while `Reference(target_type="products", ...)` is rejected (FR-006).

**Checkpoint**: All three user stories independently functional and tested.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Whole-feature validation and cleanup.

- [X] T024 [P] Run every validation scenario in [quickstart.md](./quickstart.md) against the service (envelope, terminal payload shape, widget emission, reference shape + vocab, incremental streaming, error event, auth guard) and confirm each passes.
- [X] T025 [P] Run the full quality gate and fix any fallout: `uv run ruff check app/features/chat tests/features/chat`, `uv run mypy app/features/chat`, `uv run pytest tests/features/chat -q` (Constitution Principle I; CI merge gate).
- [X] T026 [P] Check repository docs for stale streaming mentions (e.g. any reference to `data: [DONE]` or `{"type": "token", ...}` as the chat output shape) and update or remove them; confirm `specs/006-api-documentation` does not need an internal-chat-shape change (the internal contract is out of its documented scope).

---

## Phase 7: Endpoint Documentation (OpenAPI Enrichment)

**Purpose**: Bring the live `/docs` (Swagger/OpenAPI) surface in sync with the wire
contract in [contracts/chat-stream.md](./contracts/chat-stream.md). The envelope
models exist in code but are **not** wired into OpenAPI, and `router.py`'s
`responses[200]` description is stale (still describes raw text chunks). This
applies the OpenAPI-enrichment pattern spec 006 prescribed
([research.md](../006-api-documentation/research.md) §2 — document SSE via
`responses=`) to the new 009 envelope; it does **not** modify spec 006's artifacts.
Sharpens the vague doc-cleanup in T026. No behaviour changes.

- [X] T027 [P] [US1] Annotate the envelope models for schema generation: in
  `app/features/chat/schemas/events.py`, `widgets.py`, and `references.py`, add
  `Field(description=...)` to every field and
  `model_config = ConfigDict(json_schema_extra={"examples": [<one serialized example>]})`
  to each model (match the bar `app/features/chat/schemas/request.py` already
  sets). Keep serialization byte-identical. **Acceptance**: `test_schemas.py`
  extended to assert a description renders on `DonePayload.widget`,
  `DonePayload.references`, and `Reference.target_type` / `target_id`, and that the
  `examples` extra is present on at least `DoneEvent` and `AllocationSliderWidget`.
  *(Depends on T002–T004.)*
- [X] T028 [US1] Rewrite the chat route's `responses[200]` in
  `app/features/chat/router.py`: replace the stale "Each event is a UTF-8 text
  chunk … stream ends when the connection closes" text with accurate prose — the
  shared `{"event","data"}` envelope; the `token` / `done` / `error` events;
  exactly one terminal `done` carrying `content` / `widget` / `references` and
  **no** `id` (FR-003); mock-mode parity (FR-011); link to
  [contracts/chat-stream.md](./contracts/chat-stream.md). Replace the
  `{"type":"string"}` schema with one describing the envelope, and add `examples`
  showing raw SSE frames: a `token`, a `done` (with a widget + references), and
  an `error`. Sharpen the `chat` handler docstring likewise. **Acceptance**: a
  `GET /openapi.json` request shows the new description and the three examples;
  the "UTF-8 text chunk" wording is gone. *(Depends on T027 — same `router.py`
  file as no other Phase-7 task.)*
- [X] T029 [P] [US1] Tag the app and surface the contract natively: add
  `openapi_tags=[{"name": "chat", "description": "..."}, {"name": "system", ...}]`
  plus a `version` (resolved from `pyproject.toml`) and a short top-level
  `description` to the `FastAPI(...)` constructor in `app/main.py`.
  **Revision (Option A)**: the original plan called for a hand-rolled
  `app/openapi.py` override that force-registered the envelope models as
  OpenAPI `components.schemas`. That was dropped as a Principle VIII violation
  (FastAPI only auto-registers models used as real typed bodies/responses; the
  SSE envelopes are emitted as raw text, so forcing registration needs either the
  custom override or a misleading `"model":` entry). The wire contract is instead
  documented **inline** at the route level (T028's `responses[200]` envelope
  schema + `token`/`done`/`error` examples) — the single consumer's contract
  surface. No custom `app.openapi` code, no `mypy` method-assign workaround.
  **Acceptance**: `GET /openapi.json` `info` carries `version` + `description`;
  the `chat` tag renders a description in `/docs`. *(Depends on T027.)*
- [X] T030 [P] [US1] Add a docstring to `stream_chat` in
  `app/features/chat/service.py` documenting: the `token` → `done` (or `error`)
  event sequence, the leaf-only token filter (`_LEAF_NODES`), terminal-event
  assembly from `aget_state`, the `asyncio.CancelledError` (disconnect) and
  `Exception` (FR-010) branches, and the no-`id` rule (FR-003). **Acceptance**:
  `uv run ruff check app/features/chat/service.py && uv run mypy app/features/chat/service.py`
  clean; docstring present.
- [X] T031 [P] Add an OpenAPI-shape test in a new
  `tests/features/chat/test_openapi.py` (Constitution Principle I gate): via
  `TestClient(app).get("/openapi.json")` assert (a) the `/internal/chat` route's
  `responses[200]` carries the token/done/error `examples` and an envelope schema;
  (b) the `chat` tag renders a description and `info` carries `version` +
  `description`; (c) the stale "UTF-8 text chunk" string is absent from the
  operation description. **Revision (Option A)**: asserts the inline route-level
  contract surface instead of separate `components.schemas` entries (the
  custom-openapi component registration was dropped — see T029). *(Depends on T028
  and T029.)*

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately. T001 is the package scaffold.
- **Foundational (Phase 2)**: Depends on T001. T002/T003 run in parallel; T004 depends on both; T005 depends on T004; T006 depends on T005; T007 depends on T002/T003. **BLOCKS all user stories.**
- **US1 (Phase 3)**: Depends on Phase 2. All `service.py` edits are sequential (same file): T008 → T009 → T010 → T010a (disconnect) → T011 → T012. Tests: T013 (`test_chat.py`) ∥ T014 (`test_streaming.py`, different file); T014a (streaming edges) after T014 and T010a; T015 (real-Postgres integration) after T009.
- **US2 (Phase 4)**: Depends on Phase 2 (schemas + typed state). Agent tasks T016/T017/T018 are mutually parallel (different files). Integrates with US1's terminal assembly (T009) for end-to-end visibility, but agent unit tests pass independently of US1.
- **US3 (Phase 5)**: Depends on Phase 2 (T002 Reference). T021 parallel-safe with US2 tasks (different file: `analysis.py`). Integrates via US1's T009.
- **Polish (Phase 6)**: Depends on all stories being complete.
- **Docs (Phase 7)**: Depends on Phase 2 (envelope models exist). `T027 ∥ T030` (different files); after T027 → `T028` (`router.py`) ∥ `T029` (`app/openapi.py` + `main.py`); `T031` after T028 + T029.

### User Story Dependencies

- **US1 (P1)**: Foundational only. No dependency on other stories. (**MVP**)
- **US2 (P2)**: Foundational only at the unit-test level; its widgets surface through US1's terminal event end-to-end, so full-stream visibility needs US1 done.
- **US3 (P3)**: Foundational only at the unit-test level; references surface through US1's terminal event end-to-end.

### Within Each User Story

- Models before services; services before endpoints; core before integration.
- Tests written alongside (Constitution I mandates tests; mock-first, no live model/network calls).

### Parallel Opportunities

- Phase 2: T002 ∥ T003; T006 ∥ T007 (after their deps).
- Phase 3: T013 (`test_chat.py`) ∥ T014 (`test_streaming.py`) — different files; all `service.py` work (T008→T009→T010→T010a→T011→T012) and the `test_streaming.py` work (T014→T014a) are each sequential within their file.
- Phase 4: T016 ∥ T017 ∥ T018; T019 ∥ T020.
- Phase 5: T021 ∥ T022 (test can be written first); T023 parallel.
- Phase 6: T024 ∥ T025 ∥ T026.
- Phase 7: T027 ∥ T030; after T027 → T028 ∥ T029; T031 after T028 + T029.
- Across stories: US2 and US3 agent tasks touch different files (`planner.py`/`recommendation.py` vs `analysis.py`) and can proceed in parallel once Phase 2 is done.

---

## Parallel Example: Foundational + User Story 2

```bash
# Phase 2 parallel pair (different files, no shared dependency once T001 is done):
Task: "Create schemas/references.py in app/features/chat/schemas/references.py"   # T002
Task: "Create schemas/widgets.py in app/features/chat/schemas/widgets.py"          # T003

# US2 agent tasks (different files, all depend only on Phase 2):
Task: "Planner allocation widget in app/features/chat/agents/planner.py"           # T016
Task: "Recommendation product widget in app/features/chat/agents/recommendation.py"# T017
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (T001) — package scaffold, imports still resolve.
2. Complete Phase 2 (T002–T007) — models + typed state.
3. Complete Phase 3 (T008–T015, plus T010a/T014a) — streamed incremental reply + terminal `done`, error/disconnect handling, and streaming edge-case tests.
4. **STOP and VALIDATE**: `/internal/chat` emits the new envelope, real incremental tokens, one structured `done`, mock-mode parity, multi-turn continuity intact.
5. Ship/demo if ready — this alone satisfies the backend's core Conversations streaming contract.

### Incremental Delivery

1. Setup + Foundational → package and models ready.
2. Add US1 → test → ship (MVP).
3. Add US2 → widgets light up in `done`.
4. Add US3 → references light up in `done`.
5. Each story adds value without breaking the previous one (the terminal shape is fixed by US1; later stories only populate slots US1 already emits).
6. Phase 7 → the contract is visible in `/docs` (no behaviour change).

### Parallel Team Strategy

With multiple developers after Phase 2:
- Developer A: US1 (service.py stream path — the critical path).
- Developer B: US2 agents (planner.py, recommendation.py).
- Developer C: US3 (analysis.py).
Stories integrate through the shared terminal-event assembly (T009) without file conflicts.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps a task to its user story for traceability.
- Every model is a Pydantic v2 `BaseModel`; SSE framing is `f"data: {event.model_dump_json()}\n\n"` (one line per event) — no standalone SSE-helper module (Principle VIII).
- `ConversationState.widget` / `message_references` hold typed models; the `AsyncPostgresSaver` checkpointer serializes Pydantic v2 models via its `JsonPlusSerializer` — T015's multi-turn test locks this in (fallback if needed: `model_dump()` dicts reconstructed at the boundary, per [research.md](./research.md)).
- Phase 7 surfaces the envelope models in OpenAPI (the live `/docs` had fallen behind `contracts/chat-stream.md`); it sharpens the vague doc-cleanup in T026 without changing behaviour.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
