# Feature Specification: Chat Streaming Contract Alignment

**Feature Branch**: `009-chat-streaming-contract`

**Created**: 2026-07-14

**Status**: Draft

**Input**: User description: "Align the chat streaming output with the backend's documented Conversations API contract: the assistant's reply should stream incrementally token-by-token and end with a single terminal event carrying the finalized reply, any structured UI widget (e.g. budget allocation slider, product card), and any citations of the underlying financial records (transactions or statements). Django assigns the persisted message identifier after the stream completes."

## Clarifications

### Session 2026-07-14

- Q: How far should this change go — just the event envelope, real incremental streaming, or also structured widgets/ids? → A: All three: (1) correct the event envelope, (2) switch to true incremental token streaming, (3) surface widgets and references.
- Q: Who assigns the assistant message `id` carried by the terminal event? → A: Django assigns it after the stream completes, when the finalized reply is persisted; the AI service does not assign or emit the message identifier.
- Q: What shape should a citation take, and which record types can it point at? → A: Each reference is a `{target_type, target_id}` pair where `target_type` is either `transaction` or `statement` (no other reference types are produced by this feature).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The frontend receives a streamed, incremental chat reply ending in one finalized event (Priority: P1)

When the backend proxies a user's chat turn to the AI service, the assistant's reply no longer arrives as a single batch after generation finishes. Instead it streams in incrementally so the frontend can render it token-by-token as it is produced, and the stream always concludes with exactly one terminal "done" event carrying the complete finalized reply. This is the contract the backend's Conversations API documents, and it is the foundation every other chat capability depends on.

**Why this priority**: Without a correctly-shaped stream that the backend can parse and the frontend can render, no chat reply can ship. Everything else (widgets, citations) rides on top of this.

**Independent Test**: Can be fully tested by sending one chat turn and verifying the response is a sequence of incremental token events followed by exactly one terminal event containing the full reply text — with the old ad-hoc event shape entirely gone.

**Acceptance Scenarios**:

1. **Given** an authenticated chat turn, **When** the assistant produces a multi-sentence reply, **Then** the stream emits multiple token events (each carrying a fragment of the reply) as the reply is generated, followed by a single terminal event carrying the complete reply text.
2. **Given** any chat turn, **When** the stream is consumed, **Then** every event uses the shared streaming envelope — a named event type plus its data — so the backend can parse the whole stream uniformly.
3. **Given** the assistant's finalized reply, **When** the terminal event is produced, **Then** it does not contain a message identifier (the backend assigns that after persistence), but it does carry the full reply text the backend can store.
4. **Given** an unauthenticated request, **When** anyone calls the endpoint, **Then** nothing is streamed and the request is rejected.

---

### User Story 2 - Structured UI elements (widgets) travel with the finalized reply (Priority: P2)

Some replies are not just text — a budget plan is best shown as an allocation slider the user can adjust, and a set of product recommendations is best shown as rich product cards. These structured UI elements are delivered alongside the finalized reply inside the terminal event, so the frontend has everything it needs to render the rich component at the moment the reply is committed, without a second follow-up request.

**Why this priority**: Rich replies materially improve the chat experience, but plain streamed text (User Story 1) is already a usable, shippable reply on its own.

**Independent Test**: Can be fully tested by triggering a planning reply and a recommendation reply, and verifying each terminal event carries the matching widget payload (an allocation breakdown, or a list of matched products) in addition to the reply text.

**Acceptance Scenarios**:

1. **Given** a reply that proposes a budget plan, **When** the terminal event is produced, **Then** it carries an allocation widget describing the proposed per-category percentages.
2. **Given** a reply that recommends products, **When** the terminal event is produced, **Then** it carries a product widget describing the matched products.
3. **Given** a reply that is plain guidance with no rich component, **When** the terminal event is produced, **Then** the widget is explicitly null/absent so the frontend always has a consistent shape.
4. **Given** any terminal event, **When** the frontend reads it, **Then** it can always find a widget slot (even if null), never a missing field whose presence depends on the reply type.

---

### User Story 3 - Replies cite the underlying financial records they were grounded in (Priority: P3)

When the assistant answers from the user's own data, the finalized reply carries citations pointing back at the specific records it used — a transaction it referenced in a spending summary, or a statement it drew on. Each citation is a stable type-and-identifier pair so the frontend can link the user straight to the source record and the user can trust that the answer is grounded, not invented.

**Why this priority**: Citability is what distinguishes a trustworthy financial answer from a generic one, but a streamed reply (US1) with rich components (US2) is already valuable before citations are wired through.

**Independent Test**: Can be fully tested by triggering a spending-analysis reply grounded in real transactions and verifying the terminal event includes one citation per cited transaction, each identifying the record as a transaction with its identifier.

**Acceptance Scenarios**:

1. **Given** a reply grounded in the user's transactions, **When** the terminal event is produced, **Then** it includes one reference per cited transaction, each carrying the record's type (`transaction`) and its identifier.
2. **Given** a reply that draws on a statement, **When** the terminal event is produced, **Then** it includes a reference identifying that statement (type `statement`) and its identifier.
3. **Given** a reply with no grounding in specific records, **When** the terminal event is produced, **Then** the references list is empty rather than omitted, so the shape stays consistent.
4. **Given** any reference in a terminal event, **When** the frontend reads it, **Then** its type is either `transaction` or `statement` — no other reference types are produced by this feature.

---

### Edge Cases

- What happens when the reply has no text (empty content)? The stream should still emit a terminal event with an empty reply text (and appropriate widget/references), never an unclosed stream.
- What happens when the underlying model or data source fails mid-generation? A single error event (using the same shared envelope) should be emitted and the stream ended, rather than a partial reply or an open connection.
- What happens when the client disconnects mid-stream? The service should stop producing and not leave the conversation in an inconsistent state for the next turn.
- What happens in the service's mock-LLM mode? It should still emit the same event envelope (a token event followed by the terminal event) so the backend and frontend can be developed and tested against one stream shape.
- What happens when a reply both proposes a plan and references records (e.g. a plan grounded in recent transactions)? Both a widget and references should travel in the same terminal event without one precluding the other.
- What happens to multi-turn memory across the new format? A user mid-questionnaire must still be handled correctly — continuity must not regress.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: On the real (non-mock) path, the chat streaming endpoint MUST emit the assistant's reply as a sequence of incremental token events, each carrying a small fragment of the reply text, produced and sent as the reply is being generated — not as a single batch emitted only after generation completes. (Mock mode intentionally emits a single token batch — see FR-011.)
- **FR-002**: Every stream MUST conclude with exactly one terminal "done" event carrying the finalized reply: the complete reply text, any structured UI element (widget) the reply includes, and any citations (references) grounding the reply.
- **FR-003**: The terminal "done" event MUST NOT assign or emit the assistant message's identifier; message identification is the backend's responsibility and is assigned after the stream completes, when the finalized reply is persisted.
- **FR-004**: Every event on the stream — token, terminal, and error — MUST use one shared streaming envelope (a named event type together with its data), replacing the prior ad-hoc event shape, so the backend can parse the entire stream with a single consistent rule.
- **FR-005**: When a reply proposes a budget plan, the terminal event MUST carry an allocation widget describing the proposed per-category percentages; when a reply recommends products, the terminal event MUST carry a product widget describing the matched products; when a reply has no rich component, the widget MUST be explicitly null. The widget slot MUST always be present on the terminal event regardless of reply type.
- **FR-006**: A citation (reference) MUST identify one underlying financial record as either a transaction or a statement, using a stable `{target_type, target_id}` pair. No other reference types are produced by this feature.
- **FR-007**: When the assistant's reply is grounded in the user's transactions, the terminal event MUST include one reference per cited transaction, so the frontend can link the user to each source record. A reply that draws on a statement MUST include a reference identifying that statement. (No agent in this feature produces a statement reference; the `statement` target type is reserved and schema-validated so a future statement-grounded agent needs no contract change.)
- **FR-008**: When a reply is not grounded in specific records, the terminal event MUST carry an empty references list rather than omitting the slot, preserving a consistent terminal shape across every reply type.
- **FR-009**: The endpoint MUST continue to require the same authenticated, service-to-service access already required by this service's other backend-facing endpoints, and MUST reject unauthenticated requests without streaming anything.
- **FR-010**: If an error occurs while producing the reply, the stream MUST emit a single error event using the same shared envelope and then end the stream, rather than emitting a partial reply, leaving the stream open, or using a different error shape.
- **FR-011**: The shared streaming envelope and terminal-event shape MUST be identical in the service's mock-LLM mode (a token event followed by the terminal event, with widget/references slots present), so backend and frontend development and testing can proceed against one stream shape regardless of whether a real model is wired in.
- **FR-012**: Multi-turn conversation continuity (per-thread state resumption, including answers supplied mid-questionnaire) MUST continue to function across the new streaming format, so a user's ongoing conversation is not broken by this change.
- **FR-013**: This feature MUST NOT change what the service writes (or does not write) to the backend's data; it only changes the shape and incrementality of what is streamed back over the internal chat endpoint.

### Key Entities

- **Chat Stream Event**: One unit on the SSE stream, taking one of three forms — a token event (a fragment of the reply), the terminal "done" event (the finalized reply plus widget and references), or an error event — all sharing one envelope.
- **Widget**: An optional structured UI payload carried by the terminal event, rendered by the frontend — an allocation widget (proposed category percentages), a product widget (matched products), or null.
- **Reference (Citation)**: A pointer to one underlying financial record — either a transaction or a statement — expressed as a `{target_type, target_id}` pair, carried in the terminal event's references list.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of chat replies are delivered as an incremental token stream followed by exactly one terminal event — no reply arrives as a single un-streamed batch, and no stream ends without a terminal event.
- **SC-002**: For any reply whose generation yields more than one model chunk (i.e. any reply longer than a single token), the stream emits more than one token event before the terminal event, confirming the reply is genuinely incremental rather than emitted in one piece.
- **SC-003**: Every terminal event carries a widget slot (populated or null) and a references list (populated or empty), so the frontend always has a consistent, complete shape to commit — verified across general, planning, recommendation, and analysis replies.
- **SC-004**: For replies grounded in the user's financial data, 100% of the cited underlying records appear as references in the terminal event, and every reference's type is either `transaction` or `statement`, individually linkable by the frontend.
- **SC-005**: A reply proposing a budget plan always carries an allocation widget, and a reply recommending products always carries a product widget — verified across those reply types with no misses. (Refines the widget-populated cases of FR-005 / SC-003.)
- **SC-006**: The message identifier is never emitted by the AI service on the terminal event in any reply; the backend assigns it after persistence, verified by inspecting every terminal event shape.

## Assumptions

- The backend (Django) remains the only caller of this internal chat endpoint, proxies the SSE stream to the frontend, and is responsible for persisting the finalized assistant message — including assigning its identifier, sender, and created timestamp — after the stream completes. The AI service does not persist chat messages.
- The persisted message attributes the backend already maintains (sender, created_at, and any per-message `stage` label it uses) are the backend's responsibility and are out of scope for this feature; this feature changes only what the stream carries.
- "Incremental token streaming" means the reply's text is delivered to the backend as it is generated; the backend's own SSE proxy behaviour to the frontend (buffering, framing) is assumed to preserve that incrementality and is not changed by this feature.
- The widget vocabulary is limited to what this feature introduces (allocation widget, product widget, and null); additional widget types (e.g. charts) may be added later without breaking the shape, since the slot is always present.
- The reference vocabulary is intentionally limited to `transaction` and `statement` per this feature's scope; product matches surfaced via the product widget are not duplicated as references.
- The service's existing per-thread state resumption (used for multi-turn memory and mid-questionnaire answers) is reused unchanged; only the streaming presentation layer on top of it changes.
- The internal request shape the backend sends to `/internal/chat` (conversation id, user context, message, first-turn flag) is assumed to remain sufficient for producing the new terminal event; no new request fields are required from the backend for this feature.
