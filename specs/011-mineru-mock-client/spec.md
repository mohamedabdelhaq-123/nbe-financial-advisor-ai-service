# Feature Specification: Mock MinerU Client for Offline Ingestion

**Feature Branch**: `011-mineru-mock-client`

**Created**: 2026-07-15

**Status**: Draft

**Input**: User description: "Add a MockMineruClient to app/features/ingestion/mineru_client.py so that USE_MOCK_MINERU=1 actually works end-to-end, mirroring the existing MockNormalizerClient pattern (app/features/ingestion/normalizer/mock.py) and its factory gating in app/features/ingestion/normalizer/__init__.py. Currently `settings.use_mock_mineru` exists and is validated at startup in app/core/config.py, but get_mineru_client() in app/features/ingestion/mineru_client.py always returns HttpMineruClient regardless of the flag — the mock was explicitly deferred in the original feature (specs/004-document-processor/research.md §8). The new MockMineruClient must implement the MineruClient Protocol (async parse_document(file_bytes, filename) -> ParsedDocument), make no network calls, return fixed deterministic artifacts (non-empty markdown resembling a bank statement, a content_list with realistic entries — including a table entry using the `table_body` HTML key that app/features/ingestion/normalizer/chunking.py::_split_table_entry expects — and empty images), and must NOT branch on settings.use_mock_mineru internally (that branching belongs solely in get_mineru_client()). get_mineru_client() should be updated to select MockMineruClient when settings.use_mock_mineru is true, exactly mirroring get_normalizer_client()'s use_mock_llm branch. Tests should mirror tests/features/ingestion/test_normalizer.py:357-372's factory-selection test pattern, added to tests/features/ingestion/test_mineru_client.py."

## Clarifications

### Session 2026-07-15

- Q: Should the offline document-parsing capability support simulating a parsing failure (for testing error-handling paths), or should it only ever produce a successful, fixed result? → A: Success-only — it always returns the same fixed successful result; failure-path testing continues to use dedicated test doubles as it does today, not this capability. Best-effort/heuristic inspection of the actual submitted bytes was also explicitly ruled out for the same reason: it would reintroduce non-determinism, contradicting the fixed-output requirement below.
- Q: How much structured content should the offline output contain? → A: Minimal — exactly one text-like entry and one single-row table entry. Richer, multi-row content is out of scope: table-splitting/chunking behavior already has its own dedicated test coverage elsewhere, and duplicating it here would expand this feature beyond enabling offline running.
- Q: Should the offline output include any images? → A: No — the offline output always returns an empty image set. Real or placeholder image bytes carry no value for downstream text/transaction extraction and have no consumer that needs them.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run ingestion fully offline with no reachable document-parsing service (Priority: P1)

An engineer working locally, or a CI job with no network access to the document-parsing (MinerU) service, needs to exercise the full statement-ingestion flow without depending on that external service being reachable.

**Why this priority**: This is the entire point of the feature — today, enabling the existing "offline mode" setting for document parsing does nothing, so ingestion still fails outright whenever the document-parsing service is unreachable. Without this, local development and offline/CI testing of ingestion is impossible.

**Independent Test**: Enable the existing document-parsing offline-mode setting with no document-parsing service configured or reachable, then run a statement through ingestion. It can be tested independently by verifying ingestion completes and produces persisted output, with no verification of anything downstream (categorization, normalization) required.

**Acceptance Scenarios**:

1. **Given** the document-parsing offline-mode setting is enabled and no document-parsing service is reachable, **When** an engineer submits a statement document for ingestion, **Then** ingestion completes without any network call to the document-parsing service and produces parsed output (extracted text and structured content) that gets persisted.
2. **Given** the document-parsing offline-mode setting is disabled, **When** a statement document is submitted for ingestion, **Then** the system behaves exactly as it does today — it calls the real document-parsing service.

---

### User Story 2 - Verify offline/real selection is correct and consistent (Priority: P2)

A developer maintaining this system needs confidence that the offline-mode setting reliably selects the offline implementation when enabled, and the real one when disabled — with no other part of the ingestion pipeline needing to know or care which one is active.

**Why this priority**: This is what makes the offline mode trustworthy and safe to leave in the codebase — without a guarantee that the selection is correct, engineers can't trust that `USE_MOCK_MINERU=1` is actually taking effect, which is the exact bug this feature fixes.

**Independent Test**: Toggle the offline-mode setting on and off and confirm which implementation gets selected, independent of running any real ingestion flow.

**Acceptance Scenarios**:

1. **Given** the offline-mode setting is enabled, **When** the system selects a document-parsing implementation, **Then** it selects the offline implementation.
2. **Given** the offline-mode setting is disabled, **When** the system selects a document-parsing implementation, **Then** it selects the real (network-calling) implementation.

---

### User Story 3 - Offline parsing output is plausible enough for downstream processing (Priority: P3)

An engineer who enables offline document-parsing but leaves downstream transaction-extraction running in its real (non-offline) mode needs the offline parsing output to look enough like a real bank statement that downstream processing behaves normally instead of erroring out on empty or nonsensical input.

**Why this priority**: This is a refinement of the core capability — the pipeline works either way, but partial-offline configurations (mock parsing + real extraction) are a realistic combination for testing the extraction step against non-empty input without paying for a real document-parsing call.

**Independent Test**: With offline document-parsing enabled and downstream transaction-extraction left in its normal (non-offline) mode, confirm the extraction step receives non-empty, recognizable statement-like content rather than empty output.

**Acceptance Scenarios**:

1. **Given** offline document-parsing is enabled, **When** its output is inspected, **Then** it contains non-empty extracted text and the two structured content entries (one text-like, one single-row table-like) that resemble real bank-statement content (e.g., a date, merchant-like text, an amount).

---

### Edge Cases

- What happens when offline document-parsing and offline transaction-extraction are both enabled together (fully offline pipeline)? The full ingestion flow must still complete end-to-end with no network calls of either kind.
- What happens when the same document is submitted multiple times, or different documents are submitted, while offline document-parsing is enabled? Output must be identical every time — offline mode does not inspect or vary based on the actual uploaded file.
- What happens if offline document-parsing is enabled but no other offline settings are enabled? Only the document-parsing step should be affected; all other steps continue to behave exactly as they do today.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide an offline document-parsing capability that produces output in the same shape as the real document-parsing service, without making any network call, when the existing offline-mode setting is enabled.
- **FR-002**: System MUST select between the offline and real document-parsing implementation based solely on the existing offline-mode setting; no other part of the ingestion pipeline shall need to branch on or be aware of which implementation is active.
- **FR-003**: The offline document-parsing output MUST include non-empty extracted text and exactly two structured content entries resembling a real bank statement — one text-like entry and one single-row table-like entry (each carrying recognizable date, merchant-like text, and amount) — never empty or placeholder-only data. This minimal content is sufficient; it is not intended to exercise multi-row or table-splitting behavior, which has its own dedicated coverage elsewhere.
- **FR-004**: The offline document-parsing output MUST be deterministic — identical on every invocation, regardless of the submitted document's actual filename or contents.
- **FR-005**: Enabling the offline document-parsing capability MUST NOT require any new configuration beyond what already exists today (no new required settings).
- **FR-006**: The offline document-parsing capability MUST be independently toggleable from the offline transaction-extraction capability — each can be enabled or disabled without affecting the other.
- **FR-007**: System MUST continue to require a reachable document-parsing service exactly as it does today whenever the offline-mode setting is disabled (no change to existing startup validation behavior).
- **FR-008**: The offline document-parsing capability MUST NOT provide any built-in failure-simulation or content-inspection mode — it always succeeds and always returns the same fixed output regardless of the submitted bytes. Scenarios that require a failing or input-varying document-parser MUST continue to use dedicated test doubles, not this capability.

### Key Entities

- **Parsed Document Output**: The result produced by the document-parsing step for a submitted statement — extracted text/markdown, a list of structured content fragments (e.g., text and table-like entries), and any extracted images. Consumed by downstream storage and transaction-extraction steps. In offline mode, the image set is always empty — the fixed output carries text and structured content only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An engineer can run the complete statement-ingestion flow start-to-finish with no reachable document-parsing service configured, and the flow completes successfully with zero failures caused by document-parsing connectivity.
- **SC-002**: Automated verification confirms the offline implementation is selected 100% of the time when offline mode is enabled, and the real implementation is selected 100% of the time when it is disabled.
- **SC-003**: The offline document-parsing output is non-empty and statement-like in 100% of invocations, so downstream steps never report "no data found" solely because of empty offline output.

## Assumptions

- This offline capability is intended for local development, automated testing, and offline/demo environments — it is not a data source for production ingestion.
- A single fixed, non-varying output is sufficient for all offline document-parsing use cases; the offline output does not need to reflect the actual content of whatever document was submitted.
- This capability reuses the existing offline-mode setting for document parsing (already present in configuration) rather than introducing a new one, mirroring the equivalent, already-shipped offline capability for transaction extraction.
- Downstream consumers of parsed-document output do not perform strict schema validation beyond expecting text and JSON-serializable structured content, so the offline output does not need to satisfy any schema beyond that.
