# Feature Specification: Statement Transaction Normalization

**Feature Branch**: `005-statement-normalization`

**Created**: 2026-07-12

**Status**: Draft

**Input**: User description: "lets plan the second part of the ingestion pipeline which the normalization step. The normalization steps takes the id of a StatementOcrResult, and produces a normalized.json which contains the result of the normalization process. the normalization involves extracting the transactions list, extracting other info from the document. The result of the normalize endpoint would be normalized_json (returned as json, we also save it to object storage) and model_used."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extract structured transactions from a processed statement (Priority: P1)

The backend has already had a statement's raw document processed (Part 1 of this pipeline) and
holds a `StatementOcrResult` id for it. It requests normalization for that id and receives back a
structured result: the bank name, an account hint, and a list of individual transactions (date,
merchant text, category, amount, type), plus which language model produced the result.

**Why this priority**: Without this, the extracted markdown/content list from document processing
is unusable data for building a user's transaction ledger — this is the step that turns raw OCR
output into something the backend can act on.

**Independent Test**: Can be fully tested by calling the normalization endpoint with a known
`StatementOcrResult` id backed by real OCR artifacts in object storage, and verifying the response
contains a well-formed transaction list and a model identifier.

**Acceptance Scenarios**:

1. **Given** a `StatementOcrResult` id whose OCR artifacts (markdown/content list) exist in object
   storage, **When** normalization is requested, **Then** the response contains a bank name, account
   hint, transaction list, and the identifier of the model used.
2. **Given** a `StatementOcrResult` id that does not exist, **When** normalization is requested,
   **Then** the system returns a not-found error and persists nothing.
3. **Given** a statement whose content contains no identifiable transactions, **When**
   normalization is requested, **Then** the system returns a successful result with an empty
   transaction list, not an error.

---

### User Story 2 - Flag likely duplicate transactions (Priority: P2)

A statement may be reprocessed, or may overlap in date range with a previously processed
statement, so some extracted transactions may already exist in the user's ledger. Each extracted
transaction is checked against the user's existing recorded transactions and flagged when a likely
match is found, so the backend can avoid double-counting when it later imports these results.

**Why this priority**: Prevents duplicate ledger entries and the downstream reporting/budgeting
errors they'd cause, without requiring the caller to implement its own dedup logic.

**Independent Test**: Can be tested by normalizing a statement for a user who already has matching
transactions recorded, and confirming the matching extracted transactions carry a reference to the
existing transaction, while non-matching ones don't.

**Acceptance Scenarios**:

1. **Given** an extracted transaction whose account, date, and amount closely match an existing
   recorded transaction for the same user, **When** normalization completes, **Then** that
   transaction is flagged with a reference to the matching existing transaction.
2. **Given** a user with no existing recorded transactions, **When** normalization completes,
   **Then** no extracted transaction is flagged as a duplicate.

---

### User Story 3 - Consistent transaction categorization (Priority: P2)

Each extracted transaction is assigned a category drawn from a shared, maintained list of known
categories (not free text chosen ad hoc), so categorization stays consistent across statements,
users, and normalization runs, and can be extended over time without a code change.

**Why this priority**: Inconsistent or freely-invented category labels make downstream aggregation
(spending-by-category reporting, budgeting) unreliable; a shared, extensible list keeps the
vocabulary stable while still allowing new categories to be added later.

**Independent Test**: Can be tested by normalizing statements with varied merchant text and
confirming every returned transaction's category is one of the maintained list's known values.

**Acceptance Scenarios**:

1. **Given** an extracted transaction whose merchant text clearly matches a known category,
   **When** normalization completes, **Then** that category is one of the maintained list's values.
2. **Given** an extracted transaction whose merchant text doesn't clearly match any known category,
   **When** normalization completes, **Then** it is assigned a designated fallback category rather
   than an invented label.

---

### User Story 4 - Normalized result durably persisted for audit and reuse (Priority: P3)

In addition to being returned to the caller, the complete normalization result is written to object
storage at a location scoped to the statement, so it can be inspected, audited, or reused later
without re-invoking the language model.

**Why this priority**: Mirrors the durability guarantee already established for document
processing (Part 1) — the response is not the only copy of the result — but is lower priority than
the extraction and correctness behaviors above since it doesn't change what the caller receives.

**Independent Test**: Can be tested by requesting normalization and then independently reading the
resulting object back from storage, confirming it matches the returned result byte-for-byte.

**Acceptance Scenarios**:

1. **Given** a successful normalization call, **When** the resulting object storage location is
   read afterward, **Then** its contents match the JSON result returned to the caller.
2. **Given** the same `StatementOcrResult` id is normalized a second time, **When** the second call
   completes, **Then** the object at that location reflects only the latest result.

---

### Edge Cases

- What happens when the `StatementOcrResult` id is well-formed but doesn't exist? → not-found error,
  nothing persisted (User Story 1, Scenario 2).
- What happens when the OCR artifacts referenced by the `StatementOcrResult` are missing or
  unreadable in object storage? → the call fails outright; nothing is persisted or returned.
- What happens when the language model's output can't be parsed into the expected shape? → the
  call fails outright (no partial or best-guess result is persisted or returned), the same
  all-or-nothing behavior as a storage or lookup failure.
- What happens when a transaction's date or amount can't be confidently determined from the
  source content? → that entry is omitted from the result rather than guessed or left malformed.
- What happens when the same `StatementOcrResult` is normalized more than once? → the stored
  result at its location is overwritten; no version history is kept (v1).
- What happens when a caller-supplied id isn't a valid identifier at all (malformed, not just
  unknown)? → rejected immediately as a client input error, distinct from a well-formed-but-unknown
  id.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a `StatementOcrResult` identifier and resolve it to the
  previously processed statement's extracted content location before beginning normalization.
- **FR-002**: System MUST return a not-found error, persisting nothing, when the given identifier
  does not correspond to an existing OCR result.
- **FR-003**: System MUST derive the normalization result from the content already extracted during
  document processing (markdown / structured content list) and MUST NOT re-invoke the document
  processing step.
- **FR-004**: System MUST produce, per statement, a best-effort bank name and account hint when
  determinable from the source content.
- **FR-005**: System MUST produce a list of extracted transactions, each with a transaction date,
  raw merchant text, category, amount, and transaction type (debit, credit, fee, or transfer).
- **FR-006**: System MUST compare each extracted transaction against the user's existing recorded
  transactions and flag it with a reference to a likely-matching existing transaction, or indicate
  no match was found.
- **FR-007**: System MUST assign each extracted transaction's category from a shared, centrally
  maintained list of known categories rather than arbitrary free text.
- **FR-008**: System MUST assign a designated fallback category to a transaction whose source
  content does not clearly map to any known category, rather than inventing a new label.
- **FR-009**: System MUST NOT create, modify, or delete any row in a backend-owned table as part of
  normalization.
- **FR-010**: System MUST persist the complete normalization result as a single object to object
  storage, at a location scoped to the statement, alongside the artifacts already written by
  document processing.
- **FR-011**: System MUST return, to the caller, the complete normalization result together with an
  identifier of which language model produced it.
- **FR-012**: System MUST record one auditable log entry per normalization call.
- **FR-013**: System MUST require the same internal-service authentication already required by this
  service's other internal endpoints.
- **FR-014**: System MUST fail the entire call — persisting nothing new — if a complete, correctly
  shaped normalization result cannot be produced.
- **FR-015**: A statement whose source content contains no identifiable transactions MUST still
  produce a successful result with an empty transaction list, not an error.
- **FR-016**: System MUST reject a malformed (not merely unknown) identifier as a client input
  error, distinct from a well-formed-but-unknown identifier.

### Key Entities

- **StatementOcrResult** (existing, read-only): identifies which statement's extracted content to
  normalize and where it was written.
- **Statement**: the parent document being normalized; provides the account/user context needed to
  compare against existing recorded transactions.
- **Existing recorded transactions** (read-only): the user's already-known transaction history,
  read (not written) to detect likely duplicates among newly extracted transactions.
- **Category list**: a maintained, extensible set of known transaction categories that every
  extracted transaction's category is drawn from; can grow over time without requiring a code
  change.
- **Normalized result**: the bank name, account hint, and transaction list produced by one
  normalization call — returned to the caller and separately persisted to object storage; not
  stored as its own database row by this feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A normalization request for a typical multi-page statement completes within
  approximately 60 seconds.
- **SC-002**: Every transaction in a normalization result carries a category from the maintained
  category list — none are left as arbitrary free text.
- **SC-003**: When a statement overlapping a previously normalized one is reprocessed, previously
  seen transactions are correctly flagged as likely duplicates in the large majority of cases.
- **SC-004**: Zero writes to any backend-owned table occur as a result of this feature, in any
  scenario.

## Assumptions

- This is the second capability in the existing `ingestion` feature slice (alongside the
  already-implemented document-processing step from Part 1), not a new top-level feature area.
- A statement's account link is not guaranteed to be set at normalization time — bank name and
  account hint are extracted from the document content itself (FR-004) specifically because that
  linkage may still need to be established/backfilled afterward, not because the account is
  otherwise unknown.
- The normalization result is written to the same object storage bucket and statement-scoped
  location convention already established by Part 1 (no additional path segment), so both steps'
  artifacts for a given statement live under one consistent prefix.
- Duplicate detection compares transaction date (within a small tolerance) and amount against the
  user's existing recorded transactions, scoped by user rather than account (since a statement's
  account link may not yet exist at normalization time — see account-linkage note above); it does
  not involve additional language-model judgment. The exact tolerance is a planning-level detail.
- The category list is maintained by this service (not the backend) and is seeded with a starter
  set of common categories; the exact starter set and how new categories are added later are
  planning-level details.
- Only the text-based extracted content (markdown / structured content list) from document
  processing is used for normalization; extracted images are not consulted.
- This feature does not create, update, or delete rows in the backend's transaction ledger — the
  caller (backend) is responsible for acting on the returned result. Persisting actual ledger rows
  from a normalization result is a separate, later capability.
- Re-normalizing the same OCR result overwrites the previously stored result at its location; no
  version history is kept in v1.
