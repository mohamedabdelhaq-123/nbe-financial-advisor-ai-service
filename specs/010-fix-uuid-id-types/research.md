# Research: UUID Identifier Consistency

**Feature**: [spec.md](spec.md) | **Date**: 2026-07-14 | **Status**: All NEEDS CLARIFICATION resolved.

This feature had no unresolved NEEDS CLARIFICATION markers in `spec.md` — every ambiguity was resolved in the interactive clarify session and recorded at the top of the spec. The decisions below are the design-level choices that flow from those resolved clarifications: they translate "what" into "how" for `data-model.md`, the contracts, and `quickstart.md`.

---

## D1. UUID type choice — stdlib everywhere, native column type

**Decision**: Use stdlib `uuid.UUID` as the canonical Python type, SQLAlchemy's native `Uuid` column type (SA 2.0+), and Pydantic's `UUID4` annotation on every identifier surface this service owns.

**Rationale**:
- `uuid.UUID` is already the type used in the generated backend models (`Users.id`, `Products.id`, `Conversations.user_id`, etc.) — single canonical type across both bases.
- SQLAlchemy 2.0+ ships a first-class `Uuid` column type that round-trips `uuid.UUID` natively (no `TypeDecorator` needed). The project pins SA 2.0 async, so this is available without a new dependency.
- Pydantic v2's `UUID4` annotation produces the right OpenAPI schema and JSON serialization (canonical hyphenated form) and rejects malformed strings at the request boundary (fail-fast, Principle VII).

**Alternatives considered**:
- *String column + str-typed Pydantic field.* Rejected: loses native typing, invites the same drift back, complicates queries (string compare instead of native UUID compare), and the analytics slice's `str`-typed ID fields already showed how this becomes a documentation smell (the `"1001"` / `"5001"` examples).
- *Custom `UUIDTypeDecorator`.* Rejected: SA 2.0+ already ships `Uuid`; writing our own violates Principle VIII (library-first).

---

## D2. Migration strategy — amend in place

**Decision**: Amend the existing `migrations/versions/a1b2c3d4e5f6_add_phase1_and_phase2_own_tables.py` in place. Change the four affected `sa.Integer()` columns (`ai_audit_log.user_id`, `ai_problem_statements.product_id`, `ai_recommendation_logs.user_id`, `ai_recommendation_logs.product_id`) to `sa.Uuid()`. Do **not** introduce a new corrective migration.

**Rationale**:
- The migration is dated 2026-07-11 (3 days before this spec) and confirmed not deployed with real data (clarify session decision).
- Alembic's revision chain (`revision` / `down_revision`) is unchanged; only the table definitions inside `upgrade()` are edited.
- A clean re-provision (`alembic downgrade base && alembic upgrade head`, or drop-and-recreate the own DB) produces UUID-typed columns directly. This is the documented developer recovery path in `quickstart.md`.

**Alternatives considered**:
- *Append a new `ALTER COLUMN ... TYPE UUID USING ...` migration.* Rejected: it would leave a 3-day-old broken migration in history and add a corrective revision for something never deployed. Premature migration history churn.
- *Wait until deploy-time and add the corrective migration then.* Rejected: the bug is now known and would silently ship if forgotten. Fix it while it is cheap.

**Risk and mitigation**: Any developer or CI environment that has already run `alembic upgrade head` against the integer-typed schema must re-provision. `quickstart.md` documents the one-line recovery command. CI runs against a fresh Testcontainers Postgres per suite, so it is unaffected.

---

## D3. `UserContext` model — typed replacement for the opaque `initial_context` dict — **SUPERSEDED, see D11**

**Original decision (2026-07-14, no longer in effect)**: Introduce a new Pydantic model `UserContext` in `app/features/chat/schemas/request.py`. It carries `user_id: UUID4` as the only typed field and is **permissive on extras** (`model_config = ConfigDict(extra="ignore")`) so the contract does not break the moment Django adds a field this service does not yet read.

`ChatTurnRequest.initial_context: dict | None` becomes `UserContext | None`. The `chat/service.py` turn driver passes the validated model into `ConversationState["user_context"]`; agents read `state["user_context"].user_id` instead of `state["user_context"].get("user_id")`.

**Original rationale**:
- The opaque dict was the root cause of the agent-side `int()`/`str()` coercions — agents had no way to know the type, so they guessed. Typing the channel removes the reason for the casts.
- `extra="ignore"` is the right posture because Django is the source of truth for what seed context contains; this service should be a tolerant consumer, not a gatekeeper of unrelated fields.

**Why superseded**: implementing this surfaced two problems (see D11 for the full account): (1) `user_id` was now carried in *two* places — the request root and inside `initial_context` — which is redundant and invites the two copies to drift; (2) naming the model `UserContext` mislabeled the field. `initial_context`'s own docstring always said "seed context (e.g. account summary)" — genuinely open-ended conversation context, not a user-identity carrier — and the sibling `/internal/plan/*` endpoint's own `user_context: dict` field (example: `{"monthly_income": 15000}`) confirms that's what "context" means elsewhere in this codebase. A `user_id`-only model actively worked against that: Django sending richer context alongside `user_id` would have had everything except `user_id` silently dropped by `extra="ignore"`.

**Alternatives considered (at the time)**:
- *`extra="forbid"` (strict).* Rejected: would break on every Django-side addition until this service caught up. Wrong direction for a cross-service DTO.
- *Leave `initial_context` as `dict | None` and only fix the agent casts.* This is, in effect, what D11 ends up doing — but for a different reason than originally considered: not because typing was too much effort, but because `user_id` doesn't belong inside `initial_context` at all.

---

## D11. Decouple identity from conversation context; drop `is_first_turn` *(added 2026-07-15, post-implementation amendment)*

**Decision**: Two changes to the shape settled in D3:

1. **`initial_context` carries no identity field.** It reverts to a plain `dict | None` — genuinely open-ended conversation context (e.g. account summary), never `user_id`. `ConversationState` gains a root-level `user_id: uuid.UUID` field (mirroring `ChatTurnRequest.user_id`), and `ConversationState.user_context` reverts to `dict | None`. Agents (`analysis.py`, `recommendation.py`) read `state["user_id"]` directly instead of unwrapping it from a nested context object.
2. **`is_first_turn` is removed from `ChatTurnRequest` entirely.** `chat/service.py` now unconditionally calls `graph.aget_state(config)` once per turn and restores `planner_answers`, `questions_asked`, `stage`, and `user_context` from whatever it finds — empty for a genuinely new `conversation_id`, so first-turn behavior is unchanged; populated for a continuing thread. `conversation_context` is taken from `request.initial_context` when the caller supplies it, else carried forward from the prior turn's persisted value.

**Rationale**:
- `user_id` at the request root already carries validated identity (D1); duplicating it inside `initial_context` served no purpose once the UUID-typing goal was achieved directly on the root field.
- `is_first_turn` only ever saved one cheap checkpointer read. Its actual cost was correctness risk: a client sending a stale or wrong `is_first_turn` value could skip restoring real prior state (planner progress, stored context) — a class of bug with no compensating benefit once the "restore" read is understood to be cheap regardless of turn number.
- Verified live end-to-end (see quickstart.md Step 2a): two turns on the same `conversation_id`, neither request containing `is_first_turn`, correctly shared checkpointer message history, `user_id`, and the audit trail.

**Alternatives considered**:
- *Keep `UserContext` but widen it with `extra="allow"` instead of `extra="ignore"`.* Considered as a smaller fix before this decision — would have preserved extra Django-sent fields instead of silently dropping them. Superseded by the cleaner fix: don't put `user_id` in that model at all.
- *Keep `is_first_turn` for the (unimplemented) `refresh_context` semantics.* Rejected: `refresh_context` is unrelated to whether the caller supplies `initial_context`, and is — independently of this decision — not yet wired up in `chat/service.py` (a separate, pre-existing gap, out of scope here).

**Contract impact**: this is a second breaking change to the `009-chat-streaming-contract` request shape (the first being D8's `product_id` widget change). Documented in `specs/010-fix-uuid-id-types/contracts/chat-request-amendment.md`.

---

## D4. Product-title fetch location — inside `recommendations.service.match()`, not in the chat agent

**Decision**: The real product title is fetched **inside `recommendations.service.match()`**. `match()` opens its own backend DB session via `get_backend_session()` (the same pattern `analysis.py` already uses), reads `Products.title` for the matched UUIDs, and returns `ProductMatch` objects already populated with real titles.

The chat agent (`chat/agents/recommendation.py`) and the standalone router (`/internal/recommendations/match`) are unchanged in shape — they still call `match()` and get back fully-populated `ProductMatch` objects. The `str(m.product_id)` bridging cast in the chat agent is dropped (the widget payload's `product_id` is now natively `UUID4`).

**Rationale**:
- **Principle V (feature-bounded)**: the recommendations slice is the only place that owns product reads. If the chat agent reached into `Products` directly, the slice boundary would leak.
- **Symmetry with analysis agent**: `analysis.py` already opens its own backend session inline to read `Transactions`. Using the same pattern in `match()` keeps the codebase consistent.
- **Single point of change**: both callers (chat agent + standalone router) automatically get real titles. No caller-side duplication.

**Alternatives considered**:
- *Pass a backend session into `match()` from each caller.* Rejected: forces both the chat agent and the router to manage two sessions, and complicates tests at every call site.
- *Have the chat agent fetch titles after `match()` returns.* Rejected: violates Principle V (chat agent reaches into backend `Products`) and duplicates the lookup logic.

**Backend outage behavior**: if `get_backend_session()` fails or `Products` is unreachable, `match()` degrades gracefully with one consistent fallback — every match is retained and its `product_name` falls back to a fixed placeholder (`"Product unavailable"`, the `_PRODUCT_TITLE_FALLBACK` constant in `service.py`). The response shape is unchanged during a backend outage: the same matches are returned, each with a `product_name` string, so callers never see a missing field or a shorter list. The recommendation log still records each match. The principle is: a transient backend DB outage must not crash the chat turn (matches the analysis agent's `try/except` graceful-degradation pattern at `analysis.py:74`).

---

## D5. `conversation_id` intentionally left as `str`

**Decision**: `ChatTurnRequest.conversation_id: str` is unchanged. It is not promoted to `UUID4`.

**Rationale**:
- The conversation identifier is used as LangGraph's `thread_id` (`chat/service.py:61`), an opaque string key for per-thread state. It never joins to a backend column from this service.
- Promoting it would add contract churn with zero correctness benefit (Pydantic would reject slightly-malformed UUIDs that the backend might tolerate, breaking turns for no reason).
- It is mentioned in `spec.md` only to **bound** the identifier sweep, not to expand it.

**Alternatives considered**: *Promote to `UUID4` for documentation consistency.* Rejected as above.

---

## D6. Seed data + sample JSON format

**Decision**: Update `app/features/recommendations/seed.py`'s docstring and any sample seed JSON. The documented input format becomes:

```json
[
  {"product_id": "5a2c1d8e-...", "statement_text": "Need a savings account"},
  {"product_id": "9f4b2a1c-...", "statement_text": "Want to invest"}
]
```

Product IDs in seed data MUST be valid UUID strings and SHOULD correspond to real `Products.id` values on the backend (otherwise the product-title fetch returns no title).

**Rationale**: The seed CLI is a developer-run admin path, not an automated production pipeline. Re-seeding with UUID identifiers is part of validating the fix end-to-end.

**Alternatives considered**: *Auto-resolve integer IDs to UUIDs at seed time.* Rejected: there is no integer-to-UUID mapping anywhere on this service (the integer fiction was the bug), so any auto-resolution would be invented. Callers must send real UUIDs.

---

## D7. Test data — realistic UUID4 strings, not zero-UUIDs

**Decision**: All test values for `user_id` and `product_id` use realistic-looking UUID4 strings (e.g. `"3f9c9b2e-1c2a-4b3d-9e8f-2a7b6c5d4e3f"`). Tests do **not** use degenerate values like `"00000000-0000-0000-0000-000000000000"` (which would mask serialization bugs).

**Rationale**: Realistic values catch wire-layer serialization bugs (e.g. a column that silently truncates, or a Pydantic field that stringifies instead of validating) that degenerate values hide.

**Alternatives considered**: *Degenerate zero-UUIDs for brevity.* Rejected per above.

---

## D8. Breaking-change communication — chat-stream widget payload + standalone match contract

**Decision**: The `product_id` field of `ProductMatchPayloadItem` in the chat widget payload changes type from `str` to `UUID4`. This is a **breaking change** to the chat-stream contract established in spec `009-chat-streaming-contract`. The breaking change is documented in `contracts/chat-stream-amendment.md` (this feature's contracts directory) and cross-referenced from spec 009 in `tasks.md`.

The standalone `/internal/recommendations/match` endpoint never had a written contract — its `MatchRequest.user_id: int` and `ProductMatch.product_id: int` were implicit. This feature establishes that contract in writing at `contracts/recommendations-match.md`, with the corrected UUID types and a note that prior integer-typed values are no longer accepted.

**Rationale**:
- The widget payload type change is forced by the bug fix — there is no way to keep `product_id: str` while everything upstream is UUID.
- Documenting the recommendations match contract (which did not exist) is a positive side effect: it was always implicit, and now it is testable.

**Alternatives considered**: *Keep `product_id: str` on the widget payload and stringify UUIDs at the boundary.* Rejected: perpetuates the int/str/UUID three-way inconsistency the bug showed on this exact surface and leaves a str-cast at the boundary forever.

---

## D9. Analytics examples — pure documentation sweep, no type change

**Decision**: `app/features/analytics/schemas.py` keeps its `user_id: str` and `account_id: str` field types (the query paths already coerce via `uuid.UUID(...)` correctly). Only the **examples** change — from `"1001"` / `"5001"` to realistic UUID strings.

**Rationale**:
- The code paths are correct (the `jobs/*.py` modules already do `uuid.UUID(account_id)` at the query boundary — see `anomaly_detection.py:20`, `monthly_summary.py:24`, `recurring_charges.py:19`).
- The examples are misleading because they look like integers, which invited the same kind of confusion that caused the original bug. Sweeping them costs nothing and signals the convention going forward.

**Alternatives considered**: *Promote `account_id`/`user_id` to `UUID4`.* Rejected: out of scope (the underlying code is correct) and would be a breaking change to those endpoints for no correctness gain.

---

## D10. No new dependencies, no new write paths

**Decision**: This feature introduces **no new runtime dependencies** and **no new write paths to the backend DB**.

**Rationale**:
- All the types and helpers used (`uuid.UUID`, `Uuid`, `UUID4`, `get_backend_session`) already exist in the codebase or its pinned dependencies.
- The new `Products` read is a read-only access through the existing `get_backend_session()` dependency — exactly what Principle IV allows without authorization, and exactly the pattern `analysis.py` already uses for `Transactions`.

This is recorded so the Principle IV review in the implementing PR can verify it at a glance.
