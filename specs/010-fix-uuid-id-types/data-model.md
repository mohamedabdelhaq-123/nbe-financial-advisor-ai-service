# Data Model: UUID Identifier Consistency

**Feature**: [spec.md](spec.md) | **Date**: 2026-07-14

This feature is a type-consistency fix: it changes the **types** of existing identifier columns and fields across the service's own DB tables and its wire DTOs. No new tables, no new columns, no new relationships — every change below is an `Integer → Uuid` (or `int → UUID4`, or `str → UUID4`) type swap. A `UserContext` Pydantic model was introduced mid-cycle and then removed again the same cycle (see the section below and `research.md` D11) — it is not part of the final shape.

Ground truth: the backend DB identifies `Users.id`, `Products.id`, and every FK into them as `uuid.UUID`. This service's own tables and DTOs are aligned to that ground truth.

---

## Identifier entities

### User Identifier

- **Type**: `uuid.UUID` (Python), `Uuid` (SQLAlchemy column), `UUID4` (Pydantic field).
- **Backend ground truth**: `Users.id: Mapped[uuid.UUID]` (`backend_db/_generated_models.py:171`).
- **Surfaces on this service** (all `UUID` after this feature):
  - `ChatTurnRequest.user_id` — request DTO (the single source of identity; `initial_context` never carries it — see `research.md` D11)
  - `AiAuditLog.user_id` — own-DB audit table (nullable)
  - `MatchRequest.user_id` — recommendations request DTO
  - `AiRecommendationLog.user_id` — own-DB recommendation-log table
  - `ConversationState["user_id"]` — LangGraph state, root-level (added 2026-07-15; was previously nested under `user_context`)

### Product Identifier

- **Type**: `uuid.UUID` (Python), `Uuid` (SQLAlchemy column), `UUID4` (Pydantic field).
- **Backend ground truth**: `Products.id: Mapped[uuid.UUID]` (`backend_db/_generated_models.py:143`).
- **Surfaces on this service** (all `UUID` after this feature):
  - `AiProblemStatement.product_id` — own-DB problem-statement table (seed-keyed)
  - `AiRecommendationLog.product_id` — own-DB recommendation-log table
  - `ProductMatch.product_id` — recommendations response DTO
  - `ProductMatchPayloadItem.product_id` — chat widget payload

### Conversation Identifier (out of scope — documented for boundary)

- **Type**: `str` (unchanged).
- **Reasoning**: used only as LangGraph's `thread_id` (`chat/service.py:61`); never joins to a backend column. See `research.md` D5.

---

## `UserContext` — introduced then removed (superseded 2026-07-15)

The 2026-07-14 design introduced a `UserContext` Pydantic model (`user_id: UUID4`, `extra="ignore"`) to replace `ChatTurnRequest.initial_context`'s opaque `dict`. **This was reverted the same feature cycle** (`research.md` D11): `user_id` already lives, validated, on `ChatTurnRequest.user_id` at the request root — duplicating it inside `initial_context` was redundant, and naming that model `UserContext` mislabeled a field that's documented as generic, identity-unrelated conversation context (e.g. account summary). `initial_context` is now a plain `dict | None` again; see the DTO and state tables below for the current shape.

---

## Own-DB table changes (Alembic-amended)

### `ai_audit_log`

| Column | Before | After |
|---|---|---|
| `id` | `Integer PK autoincrement` | unchanged |
| `user_id` | `Integer NULL` | **`Uuid NULL`** |
| `action` | `String(255)` | unchanged |
| `detail_json` | `Text` | unchanged |
| `created_at` | `DateTime(tz=True)` | unchanged |

### `ai_problem_statements`

| Column | Before | After |
|---|---|---|
| `id` | `Integer PK autoincrement` | unchanged |
| `product_id` | `Integer NOT NULL` | **`Uuid NOT NULL`** |
| `statement_text` | `Text NOT NULL` | unchanged |
| `embedding` | `Vector(768) NULL` | unchanged |

### `ai_recommendation_logs`

| Column | Before | After |
|---|---|---|
| `id` | `Integer PK autoincrement` | unchanged |
| `user_id` | `Integer NOT NULL` | **`Uuid NOT NULL`** |
| `product_id` | `Integer NOT NULL` | **`Uuid NOT NULL`** |
| `matched_query` | `Text NOT NULL` | unchanged |
| `similarity_score` | `Float NOT NULL` | unchanged |
| `shown_at` | `DateTime(tz=True)` | unchanged |

All four column-type changes live inside the amended migration `a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py` (no new migration; see `research.md` D2). Native `Uuid` column (SQLAlchemy 2.0+) round-trips `uuid.UUID` directly — no `TypeDecorator`, no `String`-with-format-validation (Principle VIII).

---

## Wire DTO changes

### `ChatTurnRequest` (`app/features/chat/schemas/request.py`)

| Field | Before | After |
|---|---|---|
| `conversation_id` | `str` | unchanged (out of scope — D5) |
| `user_id` | `int` | **`UUID4`** |
| `message` | `str` | unchanged |
| `is_first_turn` | `bool = False` | **removed** (D11 — service now unconditionally reads prior checkpointer state) |
| `initial_context` | `dict \| None = None` | `dict \| None = None` (type unchanged; briefly became `UserContext \| None` mid-cycle, reverted — D11) |
| `refresh_context` | `bool = False` | unchanged |

### `ProductMatchPayloadItem` (`app/features/chat/schemas/widgets.py`)

| Field | Before | After |
|---|---|---|
| `product_id` | `str` | **`UUID4`** (breaking — see `contracts/chat-stream-amendment.md`) |
| `product_name` | `str` | unchanged (now sourced from `Products.title`, see below) |
| `similarity` | `float` (0.0–1.0) | unchanged |

### `MatchRequest` (`app/features/recommendations/schemas.py`)

| Field | Before | After |
|---|---|---|
| `user_id` | `int` | **`UUID4`** |
| `query` | `str` | unchanged |
| `top_k` | `int = 5` | unchanged |

### `ProductMatch` (`app/features/recommendations/schemas.py`)

| Field | Before | After |
|---|---|---|
| `product_id` | `int` | **`UUID4`** |
| `product_name` | `str` (was `f"Product {id}"`) | **`str`** (now `Products.title`, fetched in `match()`) |
| `similarity` | `float` | unchanged |

### `MonthlySummaryRequest` / `AnomalyCheckRequest` / `PostIngestionRequest` (`app/features/analytics/schemas.py`)

No field-type changes. Examples only — `"1001"` / `"5001"` → realistic UUID strings.

---

## Agent-internal state changes

### `ConversationState` (`app/features/chat/state.py`)

| Field | Before | After |
|---|---|---|
| `messages` | `Annotated[list[AnyMessage], add_messages]` | unchanged |
| `user_id` | *(did not exist)* | **`uuid.UUID`** — new root-level field, added D11 |
| `user_context` | `dict` | `dict \| None` (briefly became `UserContext`, reverted — D11; now generic conversation context, never identity) |
| `stage`, `intent`, `planner_answers`, `questions_asked`, `message_references`, `widget` | various | unchanged |

### Agent query/filter expressions (no longer coerced)

| Site | Before | After |
|---|---|---|
| `analysis.py` | `Transaction.user_id == str(user_id)`, `user_id` read from `state["user_context"].get("user_id")` | `Transaction.user_id == user_id` (UUID directly), `user_id` read from `state["user_id"]` (root-level, D11) |
| `recommendation.py` | `int(user_id) if user_id else 0`, `user_id` read from `state["user_context"].get("user_id", 0)` | `user_id` read from `state["user_id"]` directly (root-level, D11) |
| `recommendation.py` | `str(m.product_id)` (bridging cast) | `m.product_id` (already UUID) |

### `recommendations.service.match()` signature

| Param | Before | After |
|---|---|---|
| `session` | `AsyncSession` (own) | unchanged |
| `embed_fn` | callable, default `embed_texts` | unchanged |
| `user_id` | `int = 0` | **`UUID \| None = None`** |
| `query` | `str = ""` | unchanged |
| `top_k` | `int = 5` | unchanged |
| (new behavior) | — | opens a backend session internally, fetches `Products.title` for matched UUIDs, populates `ProductMatch.product_name` with the real title (graceful fallback on backend outage — see `research.md` D4) |

### `record_audit()` signature (`app/core/audit.py`)

| Param | Before | After |
|---|---|---|
| `session` | `AsyncSession` | unchanged |
| `user_id` | `int \| None` | **`UUID \| None`** |
| `action`, `detail` | unchanged | unchanged |

The three call sites that pass `user_id=None` (`transactions/service.py`, `ingestion/service/process.py`, `ingestion/service/normalize.py`) are unaffected functionally; only the type annotation moves with the signature (mypy ripple).

---

## Unchanged (correctly typed today — included to bound the sweep)

- `Users.id`, `Products.id`, `Conversations.user_id`, `Transactions.user_id`, `Transactions.account_id`, `Transactions.statement_id`, `StatementFiles.id`, `BankAccounts.id`, `ProblemStatements.product_id`, `RecommendationLogs.product_id`, all `Messages.*_id` — backend models, all already `Mapped[uuid.UUID]`. Untouched.
- `transactions/schemas.py` (`transaction_ids: list[UUID]`) and `ingestion/schemas.py` (`statement_id: UUID`) — already correct.
- `analytics/jobs/*.py` — already coerce `str` → `uuid.UUID` at the query boundary correctly; only their DTO examples were misleading (D9).
