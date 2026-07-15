# Feature Specification: UUID Identifier Consistency

**Feature Branch**: `010-fix-uuid-id-types`

**Created**: 2026-07-14

**Status**: Draft

**Input**: User description: "The AI service mistypes two backend-owned identifiers — `user_id` and `product_id` — as integers across its request contracts, its own persisted tables, and its audit log, even though the Django backend keys both `Users` and `Products` (and every foreign key into them) by UUID. The result is a service that cannot reliably attribute privileged actions to real users, cannot join its own recommendation tables back to real products, and exposes a contract internally inconsistent enough that any real UUID flowing through it would raise or silently mis-store. Fix the mismatch end-to-end so every identifier surface the service owns agrees with the backend's UUID ground truth."

## Clarifications

### Session 2026-07-14

- Q: How wide should the type fix go — chat request only, chat + audit, or everywhere `user_id`/`product_id` appears? → A: Comprehensive. Every surface on the AI service that holds or carries either identifier must be made consistent with the backend's UUID type, including the audit log, the recommendations feature (schema, own-DB tables, service, agent), and the chat widget payload.
- Q: Where should chat `user_id` come from — keep it in the request body, move it to a trusted header, or derive it from the conversations table? → A: Keep it in the request body and fix only the type. Deriving it per turn adds a hot-path read on the streaming endpoint and a first-turn race against the backend's conversation-row persistence; a header is a separate contract discussion. Minimal-risk path is: same field, correct type.
- Q: Should the untyped `initial_context` channel also be typed, or left as an opaque dict? → A: Typed. Replacing the opaque dict with a validated context model removes the root cause of the agent-side string/integer coercions that papered over the bug.
- Q: Has the own-DB migration that created the integer columns been deployed anywhere with real data? → A: No. The migration may be amended in place rather than augmented with a second `ALTER COLUMN` migration.
- Q: Once `product_id` becomes a UUID, should the recommendation agent keep fabricating a placeholder product name (`"Product {id}"`), or fetch the real title from the backend's read-only `Products` table? → A: Fetch the real title. The placeholder exists only because no product lookup was possible while the type was wrong; correcting the type removes the reason for the placeholder.

### Session 2026-07-15 (post-implementation amendment)

- Q: Now that `user_id` is a validated UUID at the request root, does `initial_context` still need to carry a `user_id` field of its own (the `UserContext` model from the 2026-07-14 session)? → A: No. **Supersedes the 2026-07-14 "Typed" answer above.** `ChatTurnRequest.user_id` is the single source of identity; duplicating it inside `initial_context` was redundant and, worse, mislabeled the field — `initial_context` is optional context *for the conversation* (e.g. account summary), not a user-identity carrier. It reverts to a plain `dict | None`; the UUID-validation win from the 2026-07-14 session is fully retained on the root `user_id` field, which is where it actually matters (audit writes, backend queries).
- Q: Is the `is_first_turn` flag still worth keeping now that `initial_context` no longer gates on it? → A: No, drop it. It only ever saved one `graph.aget_state` checkpointer lookup at the start of a turn — a single read that is cheap and, when skipped on a client's mistaken or stale flag, silently discarded real prior state (planner progress, stored conversation context). The service now unconditionally reads prior state every turn: for a genuinely new `conversation_id` this returns nothing, so first-turn behavior is unchanged; for a continuing thread it removes a class of bugs where the caller's flag disagreed with reality.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Privileged actions are attributed to the real user who performed them (Priority: P1)

Every chat turn the assistant handles is a privileged action against a real person's financial data, and the service's constitution requires that each such action be recorded in the audit log with the user it was performed for. Today the audit row's user identifier is stored as an integer, while the backend identifies the same user by a UUID — so the audit trail cannot reliably name the user a turn was for. This story makes the user identifier carried by a chat turn, persisted to the audit log, and used to ground analysis queries always be the same UUID the backend uses, so an auditor reading the log and an engineer reading the backend agree on who a turn belonged to.

**Why this priority**: Audit attribution is a constitutionally mandated, non-negotiable data-protection requirement (Principle III). If the audit log cannot name the user, no other identifier-consistency work matters — the service is already out of compliance. Everything else rides on a correctly-typed user identifier.

**Independent Test**: Can be fully tested by sending one chat turn carrying a UUID user identifier and verifying the audit row written for that turn stores the same UUID (not an integer, not a stringified integer, not a truncated value), and that an analysis query grounded in that turn's user context matches rows the backend associates with the same UUID.

**Acceptance Scenarios**:

1. **Given** a chat turn whose user identifier is a UUID, **When** the turn completes, **Then** exactly one audit row is written whose user-identifier column holds that UUID unchanged.
2. **Given** a chat turn whose user identifier is a UUID, **When** the turn is processed, **Then** the identifier is read directly from the request's root-level `user_id` field (never from `initial_context`, which carries only optional, identity-unrelated conversation context) and flows through the conversation state to the audit write and the analysis query unchanged.
3. **Given** an analysis reply grounded in the user's transactions, **When** the agent queries the backend for that user's records, **Then** it filters by the UUID directly — no string-cast, no integer-cast, no fallback — and matches the rows the backend associates with that UUID.
4. **Given** a chat turn whose user identifier is not a UUID (e.g. an integer or a malformed string), **When** the request is received, **Then** it is rejected before any privileged action runs, rather than producing a silently-wrong audit row or an empty result set.
5. **Given** the service's own audit table, **When** its schema is examined, **Then** its user-identifier column is typed to store UUID values natively, not integers.

---

### User Story 2 - Recommendations point at real products and show their real names (Priority: P2)

When the assistant recommends a product, the recommendation is only useful if it points unambiguously at a real product the backend knows about and shows that product's actual name. Today the service's recommendation tables store an integer product identifier that cannot be joined to the backend's UUID-keyed products, so the recommendation agent fabricates a placeholder name (`"Product {id}"`) because no real lookup is possible. This story makes every product identifier the service holds — in its recommendation tables, in its match response, in the rich chat widget that surfaces recommendations — be the backend's UUID, and makes the recommendation agent read the real product title from the backend's read-only products table instead of inventing one.

**Why this priority**: A recommendation that names a nonexistent product or a fabricated label is a defective user experience and a quiet correctness bug, but it is not a compliance violation; the audit-attribution fix (US1) is more urgent. Once user identifiers are correct, fixing product identifiers and the fabricated name is the natural next step to make the recommendation feature actually work end to end.

**Independent Test**: Can be fully tested by seeding problem statements keyed by UUID product identifiers, triggering a recommendation reply, and verifying the returned matches carry the same UUIDs and the real product titles from the backend's products table — with no integer-to-string bridging cast and no `"Product {id}"` placeholder anywhere in the output.

**Acceptance Scenarios**:

1. **Given** problem statements seeded against UUID product identifiers, **When** the recommendation matcher returns matches, **Then** each match carries the product's UUID unchanged and the product's real title as read from the backend's products table — never a fabricated placeholder.
2. **Given** a successful match, **When** the service logs the recommendation it showed, **Then** the logged product identifier is the same UUID the matcher used, stored natively as a UUID in the recommendation-log table.
3. **Given** a recommendation reply surfaced through the chat stream, **When** the terminal event's product widget is read, **Then** every product entry in the widget carries the product's UUID and real title, with no string/integer bridging cast at the boundary between the recommendation feature and the chat widget contract.
4. **Given** the service's two recommendation tables, **When** their schemas are examined, **Then** both the problem-statement table's product-identifier column and the recommendation-log table's product-identifier column are typed to store UUID values natively, not integers.
5. **Given** a request to the standalone recommendation match endpoint, **When** the user identifier in the request is a UUID, **Then** the request is accepted and the logged recommendation attributes the match to that UUID.

---

### User Story 3 - The public contract is internally consistent about every identifier (Priority: P3)

Beyond the two identifier columns that are actively broken, the service's public request/response contract carries several identifier-shaped fields whose examples misrepresent what the backend actually sends — examples that look like integers (`"1001"`, `"5001"`) when the real values are UUID strings. None of these are typed wrong, but their examples mislead any caller who reads them as authoritative. This story sweeps the public contract so every identifier example and field shape matches the backend's UUID ground truth, leaving no misleading examples behind.

**Why this priority**: Misleading examples are a documentation defect, not a runtime bug — the code paths coerce correctly at the query boundary. It is the lowest-priority story but is cheap to include while the team is already sweeping identifier handling.

**Independent Test**: Can be fully tested by reading every identifier-shaped example in the public request/response contract and verifying each one is a realistic UUID string, with no integer-like examples remaining.

**Acceptance Scenarios**:

1. **Given** any identifier-shaped field in the analytics request contract, **When** its example value is read, **Then** the example is a realistic UUID string (not an integer-like value such as `"1001"`).
2. **Given** any identifier-shaped field anywhere in the public contract, **When** its declared type and example are compared, **Then** they agree with the backend's UUID representation of that identifier.
3. **Given** the chat conversation identifier, **When** it is used as the thread key for multi-turn memory, **Then** it continues to resume prior turns correctly (its type is unchanged in behavior; only documentation consistency is in scope here).

---

### Edge Cases

- What happens when the existing own-DB migration has already been applied to a developer or staging database? Amending the migration in place requires a clean re-provision (drop and recreate the own DB, or `alembic downgrade base && alembic upgrade head`); this is acceptable because the migration has not been deployed with real data.
- What happens when the backend's `Products` table is unavailable at recommendation time (e.g. transient backend DB outage)? The recommendation matcher must degrade gracefully — the read-only access already used elsewhere in the service is the established pattern; a fetch failure should not crash the chat turn.
- What happens when a chat turn's optional `initial_context` is omitted on a turn after already being set on an earlier one? The service carries forward whatever context is already persisted for that conversation rather than clearing it — `initial_context` only overwrites when the caller actually supplies it.
- What happens when a user identifier arrives that is not a UUID? The request must be rejected at validation time before any privileged action or audit write runs, per the fail-fast posture the constitution requires.
- What happens to the multi-turn continuity guarantee while these identifier types change? Continuity keys on the conversation identifier (out of scope for type change) and per-thread state; only the user-identifier channel changes, so resumption behavior must not regress.
- What happens to the standalone recommendation match endpoint while its identifier types change? Both the user-identifier and product-identifier fields change type in lockstep; callers that sent integers will receive validation errors, which is the intended breaking signal.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The chat turn request MUST carry the user identifier as a UUID; any non-UUID value MUST be rejected before the turn is processed.
- **FR-002**: The chat turn request's user identifier MUST be carried exactly once, as the root-level `user_id: UUID4` field. The request's optional `initial_context` field carries only conversation context unrelated to identity (e.g. account summary) and MUST NOT duplicate `user_id`. *(Revised 2026-07-15: supersedes the original "typed `UserContext` seed-context model" requirement — see Clarifications.)*
- **FR-003**: The audit helper and the audit log table MUST accept and store the user identifier as a UUID, and a row written for a chat turn MUST persist the turn's UUID unchanged.
- **FR-004**: The analysis agent MUST filter backend records by the user identifier directly as a UUID, with no string or integer coercion at the query boundary.
- **FR-005**: The recommendation feature's request contract, response contract, own-DB problem-statement table, and own-DB recommendation-log table MUST all carry the product identifier as a UUID.
- **FR-006**: The recommendation feature's request contract, own-DB recommendation-log table, and recommendation helper MUST all carry the user identifier as a UUID.
- **FR-007**: The recommendation agent MUST read each matched product's real title from the backend's read-only products table; the fabricated `"Product {id}"` placeholder MUST be removed.
- **FR-008**: The chat widget payload that surfaces product recommendations MUST carry each product's identifier as a UUID and its real title, with no bridging cast between the recommendation feature and the chat widget contract.
- **FR-009**: The own-DB migration that created the affected identifier columns MUST be amended in place so a fresh database provisioning produces UUID-typed columns, with no second corrective migration introduced.
- **FR-010**: The seed script and any sample seed data for problem statements MUST use UUID product identifiers in their documented input format.
- **FR-011**: Every identifier-shaped example in the public request/response contract (including the analytics examples that today look like integers) MUST be a realistic UUID string consistent with the backend's identifier representation.
- **FR-012**: All existing automated tests touching the affected identifier surfaces MUST be updated to use UUID values and MUST continue to pass under the mock-first, real-Postgres integration regime the constitution requires.
- **FR-013**: The multi-turn chat continuity guarantee MUST continue to hold: a user resuming a conversation mid-questionnaire MUST be handled correctly, with only the user-identifier channel's type changing.
- **FR-014**: *(Added 2026-07-15)* The chat turn request MUST NOT require an `is_first_turn` flag. The service MUST determine prior-state existence for a `conversation_id` by reading the checkpointer directly on every turn, rather than trusting a client-supplied flag to gate that lookup.

### Key Entities *(include if feature involves data)*

- **User Identifier**: The UUID by which the backend identifies a person. Surfaces in: the chat turn request's root-level `user_id` field, `ConversationState.user_id`, the audit log row written per privileged action, the analysis agent's filter on the user's transactions, and the recommendation log row written per recommendation shown. *(Revised 2026-07-15: no longer duplicated inside `initial_context` — see Clarifications.)*
- **Product Identifier**: The UUID by which the backend identifies a product. Surfaces in: the recommendation feature's match request and response, the service's own problem-statement table (keyed by product identifier), the service's own recommendation-log table, and the chat widget payload that surfaces matched products to the user.
- **Conversation Identifier**: The UUID by which the backend identifies a chat thread. Used as the per-thread key for multi-turn memory. Its type and behavior are unchanged by this feature; it is mentioned only to bound the scope of the identifier sweep.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every identifier column the service owns in its own database (the audit log's user identifier; the problem-statement table's product identifier; the recommendation-log table's user and product identifiers) stores values natively as UUIDs after a fresh database provisioning.
- **SC-002**: Every identifier-shaped field the service exposes in its public request/response contract is declared as a UUID and accompanied by a realistic UUID example, with zero integer-like examples remaining.
- **SC-003**: An end-to-end chat turn — request through audit row through any grounded analysis query — preserves the requesting user's UUID unchanged at every hop, with no manual coercion anywhere in the path.
- **SC-004**: An end-to-end recommendation — seed through match through chat widget payload through recommendation log — preserves the product's UUID unchanged and surfaces the product's real title from the backend's products table, with no fabricated placeholder name.
- **SC-005**: The full automated test suite (mock-mode unit tests and real-Postgres integration tests) passes after the identifier-type changes, with every affected test updated to use UUID values.
- **SC-006**: The multi-turn chat continuity guarantee is verified to still hold: a user resuming a conversation mid-questionnaire is handled correctly after the identifier-type changes.

## Assumptions

- The own-DB migration that created the integer-typed identifier columns (`add_phase1_and_phase2_own_tables`) has not been deployed to any environment containing real data, so amending it in place is acceptable and preferable to introducing a corrective migration.
- The backend's `Users.id` and `Products.id` (and every foreign key into them) are and will remain UUID — confirmed against the generated backend models, and assumed stable for the foreseeable future.
- The chat conversation identifier (also a UUID on the backend) is intentionally left as a string-typed thread key on this service, because it never joins to a backend column and is only ever passed back to LangGraph's thread-state storage; tightening it is out of scope for this feature.
- The recommendation matcher's existing similarity threshold and top-k behavior are unchanged by this feature; only the identifier type and the product-title source change.
- The standalone recommendation match endpoint's callers (currently only the chat widget contract and the seed/test paths) will be updated in lockstep with the contract change; there are no external third-party callers of this internal service.
- Read-only access to the backend's `Products` table follows the same pattern the analysis agent already uses for `Transactions` (read-only session, fail-gracefully on outage), and no new write paths to the backend DB are introduced by this feature (Constitution Principle IV unchanged).
- The seed script is a developer-run admin CLI, not an automated production path, so updating its documented input format and any sample seed data carries no migration risk for existing seeded rows (rows would simply be re-seeded with UUID identifiers as part of validating the fix).
