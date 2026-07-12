# Feature Specification: Statement Document Processor

**Feature Branch**: `004-document-processor`

**Created**: 2026-07-12

**Status**: Draft

**Input**: User description: "Document processor module: given a bank statement document already uploaded and recorded by the backend (identified by a statement reference), extract its content via an external document-parsing engine (MinerU) and persist the extracted artifacts (markdown text, structured content list, and images) to object storage under a dedicated bucket, keyed by a prefix scoped to that statement. The processor returns the storage location (key prefix) of the persisted artifacts and a fixed identifier of which OCR engine performed the extraction, so the backend can record where the extracted content lives without this service writing to backend-owned tables. Normalization/column-mapping of extracted content into transactions, confidence scoring, image analysis, and any user-facing or Django-facing endpoint outside this internal processing step are out of scope."

> **Scope guard**: This capability is consumed internally by the Django backend (the direct
> caller); the ultimate beneficiary is the end user of the personal-finance product, reached
> *through* Django after the backend normalizes and surfaces the extracted content. This service
> is never exposed to the end user directly. Turning extracted content into structured transaction
> data (normalization/column-mapping) is a separate, later capability and is explicitly out of
> scope here — this spec covers extraction and durable persistence of the raw extraction output
> only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extract content from an uploaded statement (Priority: P1)

As the backend system, after a user has uploaded a bank statement document, I need to have its
content extracted into a readable, structured form, so that a later step can turn it into
transaction data without every downstream consumer needing to parse the original document format
itself.

**Why this priority**: Without extraction, no other capability in the ingestion pipeline can
proceed — this is the foundational step that unlocks everything after it.

**Independent Test**: Given a statement reference for a document that was previously uploaded and
recorded, request processing for it and confirm a successful result is returned identifying where
the extracted content now lives.

**Acceptance Scenarios**:

1. **Given** a statement reference for a previously uploaded, readable document, **When**
   processing is requested, **Then** the extracted content is produced and a successful result
   identifying its storage location is returned.
2. **Given** a statement reference for a document containing tables (transaction line items),
   **When** processing is requested, **Then** the extracted result preserves the tabular structure
   of that content, not just flattened text.

---

### User Story 2 - Persist extracted artifacts durably, without touching backend records (Priority: P2)

As the backend system, I need the extracted content to be saved somewhere durable and addressable,
so that I can retrieve it later and record its location myself, without this capability needing
write access to my own records.

**Why this priority**: The extraction in User Story 1 is worthless if its output disappears after
the request completes; durable, backend-independent persistence is what makes the result usable by
later steps and other consumers.

**Independent Test**: After a successful processing result, independently fetch the extracted
artifacts from the returned storage location and confirm the markdown content, structured content
listing, and any images are all present there.

**Acceptance Scenarios**:

1. **Given** a successful processing result, **When** the returned storage location is inspected,
   **Then** it contains the extracted markdown text, a structured content listing, and any images
   found in the document.
2. **Given** a successful processing result, **When** the backend records the returned storage
   location, **Then** this capability has made zero writes to any backend-owned record in the
   process.

---

### User Story 3 - Fail explicitly when extraction cannot succeed (Priority: P3)

As the backend system, I need to be told clearly when a statement's content could not be
extracted, so that I can retry, alert an operator, or route around the failure instead of
believing extraction succeeded when it did not.

**Why this priority**: Silent or ambiguous failure is worse than no capability at all — it lets
bad data flow further downstream before anyone notices. This is lower priority than the core
success path but is still required for the capability to be trustworthy.

**Independent Test**: Request processing for a statement reference that cannot be fulfilled (e.g.
the underlying document is missing from storage, or the external processing engine is
unreachable) and confirm an explicit, distinguishable failure is returned rather than a partial or
silent success.

**Acceptance Scenarios**:

1. **Given** a statement reference unknown to backend records, **When** processing is requested,
   **Then** the request is rejected before any external processing is attempted.
2. **Given** a valid statement reference whose underlying document cannot be retrieved from
   storage, **When** processing is requested, **Then** an explicit failure is returned identifying
   that the source document could not be read.
3. **Given** a valid statement reference, **When** the external document-processing engine is
   unreachable or returns an unusable result, **Then** an explicit failure is returned rather than
   an incomplete or fabricated extraction result.

---

### Edge Cases

- What happens when the statement reference does not correspond to any record the backend has
  ever created? The request MUST be rejected before any external call is attempted.
- What happens when the statement record exists but its underlying document is missing or
  unreadable from storage? An explicit failure MUST be returned identifying the source-retrieval
  problem, distinct from an extraction-engine problem.
- What happens when the external document-processing engine is unreachable, times out, or returns
  an error? An explicit failure MUST be returned rather than an empty or partial result.
- What happens when the document yields no extractable content (e.g. a blank or fully corrupted
  file)? The system MUST still return a result reflecting that outcome rather than raising an
  ambiguous internal error.
- What happens when the same statement is processed more than once? The system MUST complete
  successfully each time and the extracted artifacts at the statement's storage location MUST
  reflect the most recent successful processing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept, from the backend, a reference identifying which previously
  uploaded statement document to process.
- **FR-002**: System MUST retrieve the referenced document's original content from storage before
  attempting extraction.
- **FR-003**: System MUST send the retrieved document to an external document-processing engine to
  extract its textual and tabular content.
- **FR-004**: System MUST persist the extracted markdown text, structured content listing, and any
  images found in the document to a durable storage location scoped uniquely to that statement.
- **FR-005**: System MUST return to the caller the storage location of the persisted extracted
  artifacts and a fixed label identifying which processing engine produced them.
- **FR-006**: System MUST reject a processing request that references a statement unknown to
  backend records, before attempting to contact the external processing engine.
- **FR-007**: System MUST return an explicit, distinguishable failure when the source document
  cannot be retrieved, when the external processing engine is unreachable, or when it returns an
  unusable result — rather than a partial or silent success.
- **FR-008**: System MUST require the caller to be authenticated, consistent with every other
  internal capability of this service.
- **FR-009**: System MUST NOT write to any backend-owned record — recording where extracted
  artifacts live is the backend's own responsibility, using the location this capability returns.
- **FR-010**: System MUST NOT include extracted images inline in its response to the caller;
  images are only made available via the persisted storage location.
- **FR-011**: System MUST NOT attempt to interpret or map extracted content into structured
  transaction data — that is a separate, later capability.

### Key Entities

- **Statement Document**: The previously uploaded bank-statement file this capability processes,
  identified by a reference the backend provides. Owned and tracked by the backend; this
  capability only reads it.
- **Extracted Content Artifacts**: The markdown text, structured content listing, and images
  produced by processing one statement document. Persisted together under a single storage
  location scoped to that statement.
- **Processing Result**: The outcome returned to the caller for one processing request — the
  storage location of the extracted artifacts and the identifier of the engine that produced them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a valid, previously uploaded statement, the caller receives the location of its
  extracted content within 60 seconds for a typical multi-page statement.
- **SC-002**: 100% of requests referencing an unknown statement are rejected before any external
  processing attempt is made.
- **SC-003**: 100% of extraction failures (unreachable engine, unreadable source, unusable result)
  surface as an explicit, distinguishable error rather than a partial or silent success.
- **SC-004**: 100% of successful processing results have their extracted artifacts immediately
  retrievable from the returned storage location, with no additional propagation delay.
- **SC-005**: This capability makes zero writes to backend-owned records across all of its
  operations.

## Assumptions

- The external document-processing engine used is MinerU, called synchronously (one blocking
  call per document) rather than through an asynchronous submit-and-poll pattern.
- Extracted artifacts are persisted using this service's existing object-storage capability, in a
  bucket dedicated to extraction output (`pfm-statements-ocr`), keyed by a prefix scoped to the
  statement reference (e.g. `pfm-statements-ocr/{statement_id}/`).
- This capability resolves the statement's original-document storage location itself, via its
  existing read-only access to backend records, given only a statement reference from the caller —
  the backend does not need to supply the storage location directly.
- Confidence scoring of extraction quality is out of scope for this capability and is left for a
  later step or a default value.
- Images are persisted to storage but are never analyzed or transformed by this capability, only
  passed through from the processing engine's output.
- Re-processing the same statement reference overwrites the previously persisted artifacts at that
  statement's storage location; no versioning of prior extraction attempts is required.
- Normalization/column-mapping of extracted content into structured transaction data, and any
  endpoint exposing that mapped data, are separate, later capabilities not covered here.
