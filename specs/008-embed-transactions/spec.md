# Feature Specification: Transaction Embedding by ID

**Feature Branch**: `008-embed-transactions`

**Created**: 2026-07-14

**Status**: Draft

**Input**: User description: "current we have write access on transactions table's embedding column, and have crud on the monthly summaries table, currently I want to implement an endpoint to embed transactions give their ids, and saves it to the db directly, what do you think?"

## Clarifications

### Session 2026-07-14

- Q: What text should represent a transaction when computing its embedding? → A: Structured summary — merchant + category + amount + currency + date combined into one line, consistent with the existing monthly-summary embedding pattern.
- Q: How should a batch with some invalid/nonexistent transaction IDs be handled? → A: All-or-nothing — the entire request is rejected and nothing is written if any submitted ID is invalid; the response identifies the invalid IDs.
- Q: Should each embedding write be recorded to the audit log? → A: Yes, one audit log entry per request, capturing which transaction IDs were targeted.
- Q: What is the maximum number of transaction IDs allowed per request? → A: 500, enforced as a hard per-request cap; the call is synchronous and blocks until all embeddings are written or the whole batch fails.
- Q: Does the server-constructed transaction summary (merchant/category/amount/currency/date) need redaction before it reaches the embedding provider? → A: No redaction — sent as-is, consistent with the existing monthly-summary embedding pattern, which sends comparable structured financial data to the same configured provider.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Backend requests embeddings for newly ingested transactions (Priority: P1)

After a statement is ingested and its transactions exist in the backend's system, the backend calls this service with the list of new transaction IDs. The service computes an embedding for each transaction and stores it directly against that transaction's record, so the transactions immediately become usable for semantic search and retrieval features without the backend having to ferry vectors back and forth itself.

**Why this priority**: This is the endpoint's entire reason to exist — without it, transactions have no embeddings and nothing downstream (semantic search, similarity-based insights) can use them.

**Independent Test**: Can be fully tested by calling the endpoint with a batch of valid transaction IDs and verifying that each corresponding transaction's stored embedding is populated afterward.

**Acceptance Scenarios**:

1. **Given** a set of transaction IDs that exist and currently have no embedding, **When** the backend calls the endpoint with those IDs, **Then** each transaction's embedding is computed and persisted, and the response confirms which IDs succeeded.
2. **Given** a single transaction ID, **When** the backend calls the endpoint, **Then** that transaction's embedding is computed and persisted.
3. **Given** an unauthenticated request, **When** anyone calls the endpoint, **Then** the request is rejected and no embeddings are computed or written.

---

### User Story 2 - Backend re-embeds existing transactions (Priority: P2)

The backend can call the same endpoint with IDs of transactions that already have a stored embedding (for example, after the embedding model or vector size changes, or after a transaction's details were corrected), and the service overwrites the existing embedding with a freshly computed one.

**Why this priority**: Keeps previously embedded transactions from going stale, but the service is already useful for first-time embedding (User Story 1) without this.

**Independent Test**: Can be fully tested by embedding a transaction, calling the endpoint again for the same ID, and verifying the stored embedding is replaced rather than duplicated or rejected.

**Acceptance Scenarios**:

1. **Given** a transaction that already has a stored embedding, **When** the backend requests it be embedded again, **Then** the existing embedding is overwritten with the newly computed one.

---

### User Story 3 - Backend gets a clear, actionable rejection for an invalid batch (Priority: P3)

If the backend submits a batch that includes one or more transaction IDs that don't exist, the entire batch is rejected with no embeddings written, and the response clearly identifies exactly which IDs were invalid so the backend can correct and resubmit the batch.

**Why this priority**: Improves reliability and debuggability of batch calls, but the core embedding capability (User Stories 1-2) delivers value even in the simple case where every submitted ID is valid.

**Independent Test**: Can be fully tested by submitting a batch with some valid and some invalid transaction IDs and verifying the request is rejected as a whole, with the response naming the invalid IDs and no transaction in the batch ending up with a newly written embedding.

**Acceptance Scenarios**:

1. **Given** a batch containing both existing and nonexistent transaction IDs, **When** the backend calls the endpoint, **Then** the entire request is rejected, no transaction's embedding is written, and the response identifies which IDs were invalid.

---

### Edge Cases

- What happens when the request contains an empty list of transaction IDs?
- What happens when the request contains the same transaction ID more than once?
- What happens when the number of transaction IDs in one request exceeds the 500-ID cap? (Rejected outright per FR-013, nothing written.)
- What happens when the underlying embedding provider is unreachable or errors partway through an otherwise-valid batch — is the batch left with some transactions embedded and others not, or is the operation atomic (all succeed or none do)?
- What happens when a transaction exists but has little or no descriptive data (e.g., missing merchant/category)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose an endpoint that accepts a list of transaction IDs from the backend and computes and stores an embedding for each corresponding transaction.
- **FR-002**: The endpoint MUST require the same authenticated, service-to-service access already required by this service's other backend-facing endpoints, and MUST reject unauthenticated requests without computing or writing anything.
- **FR-003**: For each valid transaction ID, the system MUST derive a textual representation of that transaction as a structured summary combining its merchant, category, amount, currency, and date, compute an embedding vector from that text, and persist the vector directly to that transaction's stored embedding. This summary MUST be sent to the embedding provider as-is, with no server-side redaction, consistent with the existing monthly-summary embedding pattern.
- **FR-004**: The system MUST reject requests that contain no transaction IDs with a clear, actionable error, and MUST NOT compute or write anything for such a request.
- **FR-005**: The system MUST NOT modify any part of a transaction's record other than its stored embedding value.
- **FR-006**: When a request includes one or more transaction IDs that do not exist, the system MUST reject the entire request, write no embeddings for any transaction in that request, and identify in the response which submitted IDs were invalid.
- **FR-007**: The system MUST support re-embedding a transaction that already has a stored embedding, replacing the previous value rather than duplicating it or rejecting the request.
- **FR-008**: The system MUST support embedding multiple transaction IDs within a single request.
- **FR-009**: The system MUST report back, per requested transaction ID, that its embedding was successfully computed and stored on a successful request, so the backend does not need to separately verify the outcome.
- **FR-010**: When the embedding computation fails partway through an otherwise-valid batch (e.g. the underlying embedding provider becomes unreachable), the operation MUST be atomic: either every transaction in the batch ends up with its newly computed embedding stored, or none of them do, and the failure is reported to the caller.
- **FR-011**: The system MUST compute transaction embeddings using the same centrally managed embedding configuration (provider, model, vector size) as the rest of the service, so transaction embeddings remain comparable with embeddings produced elsewhere in the system.
- **FR-012**: The system MUST record one audit log entry per request, capturing which transaction IDs were targeted, when a batch of transactions is successfully embedded.
- **FR-013**: The system MUST reject requests containing more than 500 transaction IDs with a clear, actionable error, and MUST NOT compute or write anything for such a request. The endpoint MUST process an accepted request synchronously, returning only once every transaction in the batch has succeeded or the batch has failed as a whole.

### Key Entities

- **Transaction**: An existing, backend-owned financial record (already created by statement ingestion) that this feature reads selected descriptive fields from and to which it writes back exactly one value: its embedding.
- **Transaction Embedding Request**: The list of transaction IDs submitted by the backend in a single call, to be embedded and persisted.
- **Transaction Embedding Result**: The per-transaction outcome of a request — whether that transaction's embedding was successfully computed and stored, or why it failed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The backend can request embeddings for a batch of up to 500 transaction IDs (the maximum allowed per request) in a single synchronous call and receive a definitive result before the call returns.
- **SC-002**: Immediately after a successful call, 100% of the transaction IDs reported as succeeded have a retrievable, non-empty stored embedding — no further delay or follow-up call is needed.
- **SC-003**: A batch containing any invalid transaction ID is rejected as a whole — no transaction in that batch ends up with a newly written embedding — and the response clearly identifies which submitted IDs were invalid.
- **SC-004**: No transaction's non-embedding data is ever altered as a result of using this feature, verified across repeated calls including re-embedding.

## Assumptions

- The transaction IDs submitted are assumed to already belong to users the backend is authorized to act on; this service does not perform its own per-user authorization check beyond validating that each transaction ID exists, since the caller is the trusted backend itself (service-to-service authentication only, consistent with this service's other backend-facing endpoints).
- Duplicate transaction IDs within the same request are treated as a single embedding operation for that transaction (the transaction is embedded once, and its result is reported once), consistent with FR-007's overwrite behavior.
- This feature reuses the service's existing shared embedding capability (used elsewhere in the service for computing vectors) rather than introducing a separate embedding path, per FR-011.
- The transaction fields available for building the embedding text are limited to those already selected and mapped for this service's read access to the backend's transactions table.
