# Data Model: Chat Streaming Contract Alignment

**Feature**: [spec.md](./spec.md) | **Date**: 2026-07-14

No new tables are introduced and no existing table is changed. This feature
promotes `app/features/chat/schemas.py` to a `schemas/` package and adds
first-class Pydantic models for the stream contract. The only in-memory
LangGraph state shape (`ConversationState`) gains typed fields. Everything
below is a transient DTO/contract value, not a persisted entity. The own-DB
checkpointer tables (`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`)
persist whatever `ConversationState` holds, unchanged in schema — `widget`
and `message_references` are serialized state values (Pydantic v2 models,
supported by the saver's `JsonPlusSerializer`), not columns.

## ConversationState (existing, in-memory — typed fields)

Source: `app.features.chat.state.ConversationState` (TypedDict). The
`messages` reducer (`add_messages`) and all existing keys are unchanged.

| Field | Type | Status | Rule |
|---|---|---|---|
| `messages` | `Annotated[list[AnyMessage], add_messages]` | unchanged | Append/merge by id; the leaf agent appends its `AIMessage` reply here |
| `user_context` | `dict` | unchanged | Seed context (user_id, etc.) |
| `stage` | `str` | unchanged | `"planning"` / `"plan_complete"` / `""` — internal routing signal |
| `intent` | `str` | unchanged | Set by Maestro; consumed by the router, never streamed |
| `planner_answers` | `dict` | unchanged | Questionnaire answers accumulated across turns |
| `questions_asked` | `int` | unchanged | Drives the planner questionnaire |
| `message_references` | `list[Reference]` | **reshaped + typed** | Was `list[dict]` of `{table, id}`; now typed `Reference` objects |
| `widget` | `Widget \| None` | **added + typed** | `None` unless the leaf agent set it; typed union, not a dict |

## Reference (new — `schemas/references.py`)

```python
TargetType = Literal["transaction", "statement"]

class Reference(BaseModel):
    target_type: TargetType
    target_id: str
```

| Field | Type | Rule |
|---|---|---|
| `target_type` | `Literal["transaction", "statement"]` | The only two types this feature produces (FR-006) |
| `target_id` | `str` (UUID) | UUID only — no PII (Principle III) |

**Producer mapping**:
- `analysis` → one `Reference(target_type="transaction", target_id=...)` per
  cited transaction (FR-007).
- `recommendation` → no references (matches live in the `product_card`
  widget payload).
- No agent currently emits a `statement` reference; the type is reserved so a
  future statement-grounded agent needs no contract change.

## Widget (new — `schemas/widgets.py`, discriminated union)

```python
class AllocationSliderWidget(BaseModel):
    type: Literal["allocation_slider"] = "allocation_slider"
    payload: AllocationSliderPayload        # {allocations: [{category, percentage(0-100)}]}

class ProductCardWidget(BaseModel):
    type: Literal["product_card"] = "product_card"
    payload: ProductCardPayload             # {products: [{product_id, product_name, similarity(0-1)}]}

Widget = AllocationSliderWidget | ProductCardWidget
```

| Producer | Widget emitted |
|---|---|
| `planner` (on `plan_complete`) | `AllocationSliderWidget` mirroring `BudgetAllocation` (percentages sum to 100) |
| `recommendation` | `ProductCardWidget` mirroring `ProductMatch` (up to `top_k`=3) |
| `analysis`, `general`, `planner` while asking | `None` |

The terminal `done` event always carries the slot (`Widget | None`),
satisfying FR-005.

## ChatStreamEvent (new — `schemas/events.py`, three envelope models)

Each model serializes to one SSE `data: {json}\n\n` line via
`model_dump_json()`.

```python
class TokenEvent(BaseModel):
    event: Literal["token"] = "token"
    data: str                               # a reply fragment

class DonePayload(BaseModel):
    content: str
    widget: Widget | None = None
    references: list[Reference] = Field(default_factory=list)

class DoneEvent(BaseModel):
    event: Literal["done"] = "done"
    data: DonePayload                        # NOTE: no `id` field (FR-003)

class ErrorPayload(BaseModel):
    message: str

class ErrorEvent(BaseModel):
    event: Literal["error"] = "error"
    data: ErrorPayload
```

| Event | `data` shape | When |
|---|---|---|
| `token` | raw string — a fragment of the reply | Per incremental `AIMessageChunk` from a leaf agent (real path); one event with the whole reply (mock path) |
| `done` | `DonePayload` — `content`, `widget`, `references`; **no `id`** | Exactly once, after the stream drains (FR-002, FR-003) |
| `error` | `ErrorPayload` — `message` | Exactly once on a production failure, then the stream closes (FR-010) |

**Validation rules**:
- `DonePayload.widget` and `DonePayload.references` are always present
  (nullable / empty list) — never omitted (FR-005, FR-008).
- `DonePayload` has no `id` field by construction (FR-003).
- A turn's stream emits at most one `done` and at most one `error` (SC-001).

## ChatTurnRequest (existing — moved into the package, unchanged)

Source: `app/features/chat/schemas/request.py` (moved from `schemas.py`,
re-exported from `schemas/__init__.py`). No field is added, removed, or
retyped; the request shape the backend sends to `/internal/chat` is already
sufficient to produce the new terminal event (see spec Assumptions).
