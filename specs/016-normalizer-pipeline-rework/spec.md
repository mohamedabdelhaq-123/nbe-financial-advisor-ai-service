# Feature Specification: Normalizer Pipeline Rework

**Feature Branch**: `016-normalizer-pipeline-rework`

**Created**: 2026-07-23

**Status**: Draft

**Input**: User description: "Improve the statement-normalization agent in the ingestion feature: align the normalized output with what the backend's transaction/account schema actually expects (a structured key-value map for additional facts instead of a list of pairs, a real unmasked account number instead of a masked hint), present source statement content to the extraction model in a cleaner, lower-noise form instead of raw JSON-wrapped markup, replace the current strictly-sequential/manually-batched extraction with genuine bounded concurrent processing, and size extraction chunks by the actual output-risk driver (transaction count) instead of an indirect character-count proxy — while keeping the codebase organized so more than one extraction strategy can be added later."

## Clarifications

### Session 2026-07-23

- Q: FR-002 now puts a real, unmasked account number into the model's input/output, which this
  service's existing global auto-instrumentation will capture into tracing telemetry by default.
  Today's telemetry redaction only recognizes card/phone/email shapes, not bank account numbers,
  and Constitution Principle III requires unconditional minimization for any telemetry copy. Should
  this feature also extend telemetry redaction to cover account-number-shaped values? → A: No —
  track the redaction gap as a separate, later follow-up; out of scope for this feature.
- Q: Under the new concurrent extraction design, if one extraction portion exhausts its retries
  while other portions running alongside it have already succeeded, should the request still fail
  as a whole (today's all-or-nothing behavior), or should it return whatever portions succeeded? →
  A: All-or-nothing stays — any portion's exhausted retries fails the entire normalization request,
  unchanged from today's sequential behavior; no partial result is ever returned.
- Q: SC-003/SC-004 used unquantified language ("meaningfully less," "large multi-page statement") —
  should they carry a concrete size/speedup target, and if so, based on what reference? → A: Anchor
  to this codebase's existing real-world validation benchmark (a 3+ page, 40+ transaction statement,
  per research.md's original normalization validation) with a ≥2x speedup target at raised
  concurrency and zero truncated portions at that size.

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Normalized output matches the backend's real data model (Priority: P1)

The backend requests normalization of a statement and receives back a result whose shape already
matches what its own transaction and account records expect, rather than a shape the backend has to
transform before it can use it. Any additional facts the model finds beyond the minimum documented
shape (per transaction or per statement) come back as a plain key-value map, not a list of
individual key/value entries.

**Why this priority**: This is the blocking integration problem — the backend cannot reliably
consume today's output without extra translation work, which defeats the purpose of a normalization
step. Nothing else in this feature matters if the shape handed to the backend is still wrong.

**Independent Test**: Can be tested by normalizing a statement with known additional facts (e.g. an
opening balance, a reference number) and confirming those facts arrive as directly-addressable
key-value pairs in the result, with no list-of-pairs wrapper anywhere in the output.

**Acceptance Scenarios**:

1. **Given** a statement whose source content contains facts beyond the minimum documented
   transaction/statement shape, **When** normalization completes, **Then** those facts appear as a
   key-value map (not a list of `{key, value}` entries) at both the transaction level and the
   statement level.
2. **Given** a statement with no additional facts beyond the minimum shape, **When** normalization
   completes, **Then** no empty or placeholder key-value collection is included.

---

### User Story 2 - Real account number instead of a masked hint (Priority: P1)

The backend receives the account number exactly as it appears in the source statement — not a
masked or partially-redacted approximation — so it can reliably match the statement to an existing
account or create a new one.

**Why this priority**: A masked value cannot be used for reliable account matching or linkage; this
is as fundamental to the backend being able to act on the result as User Story 1.

**Independent Test**: Can be tested by normalizing a statement whose source content states a full
account number and confirming the returned value matches the source digits exactly, with no masking
applied.

**Acceptance Scenarios**:

1. **Given** a statement whose source content states an account number, **When** normalization
   completes, **Then** the returned account number matches the source value exactly (no masking,
   truncation, or redaction).
2. **Given** a statement whose source content does not state an account number anywhere, **When**
   normalization completes, **Then** the account number is absent/null rather than guessed.

---

### User Story 3 - Faster processing through real concurrent extraction (Priority: P2)

A statement with many extraction portions is processed with more than one portion in flight at a
time, up to an operator-configurable safety limit, instead of always one at a time by default —
without changing which transactions come out the other end.

**Why this priority**: Directly reduces how long the backend waits for a normalization result on
larger statements, but doesn't change correctness or the output contract, so it's independently
valuable but not blocking.

**Independent Test**: Can be tested by normalizing the same large statement once with the
concurrency limit raised and once with it at its most conservative setting, confirming both runs
produce the same extracted transactions but the higher-concurrency run completes faster.

**Acceptance Scenarios**:

1. **Given** a statement large enough to be split into several extraction portions and a
   concurrency limit greater than one, **When** normalization runs, **Then** more than one portion
   is processed at the same time and the total result is identical in content to a fully sequential
   run of the same statement.
2. **Given** the concurrency limit is left at its most conservative default, **When** normalization
   runs, **Then** behavior is unchanged from today's fully-sequential processing.

---

### User Story 4 - Chunking sized by what actually risks a bad extraction (Priority: P2)

A statement's content is divided into extraction portions primarily by how many transactions a
portion is likely to contain, rather than by the raw character length of the underlying source
markup — so portion size tracks the thing that actually risks an incomplete or truncated
extraction, not an indirect proxy for it.

**Why this priority**: Reduces truncated/incomplete extractions on real statements (particularly
ones with long non-Latin merchant text, which inflates character-based measurements without
inflating actual extraction output) without requiring a new capability from the caller's
perspective.

**Independent Test**: Can be tested by normalizing a statement containing rows with very long
merchant-name text and confirming portioning tracks row count rather than producing unusually small
or large portions purely because of text length.

**Acceptance Scenarios**:

1. **Given** a table of transactions with wide variance in per-row text length, **When** the
   statement is divided into extraction portions, **Then** portion boundaries track transaction
   count rather than varying erratically with row text length.
2. **Given** a single row whose content is unusually large even on its own (e.g. an exceptionally
   long description), **When** portioning happens, **Then** a fallback size safeguard still applies
   so that one oversized row cannot silently break extraction.

---

### User Story 5 - Room for more than one extraction strategy over time (Priority: P3)

The system can gain an additional way of turning statement content into a normalized result (for
example, a different strategy better suited to a different kind of statement) without changing how
the backend calls normalization or what shape it gets back, and without disturbing the strategy
already in place.

**Why this priority**: Not needed for today's behavior to work correctly, but avoids the current
extraction approach becoming an obstacle to future improvement; lowest priority since it delivers no
immediate change in behavior.

**Independent Test**: Can be verified by confirming the normalization endpoint's request/response
contract stays identical regardless of which extraction strategy is active, and that swapping the
active strategy is a configuration change, not a call-site change.

**Acceptance Scenarios**:

1. **Given** more than one extraction strategy exists in the system, **When** the active strategy is
   changed, **Then** the normalization endpoint's request and response shapes are unaffected.
2. **Given** a new extraction strategy is added, **When** it is added, **Then** no existing strategy's
   behavior or output changes as a result.

---

### User Story 6 - Full observability into per-statement extraction cost and behavior (Priority: P2)

Every LLM call made while normalizing one statement — across however many chunks are processed,
including when several run concurrently — is visible together as one coherent, traceable unit,
tagged with enough business context (which statement, which chunk, which prompt version) to debug a
bad extraction or explain its cost after the fact.

**Why this priority**: The pipeline redesign (Stories 3 and 4) changes execution shape from strictly
sequential to genuinely concurrent — exactly the kind of change that can silently degrade how well
an existing tracing setup groups related work together. Validating this now is far cheaper than
discovering it during a production debugging session.

**Independent Test**: Can be tested by normalizing a statement large enough to produce several
concurrently-processed chunks and confirming every resulting LLM call appears grouped under one
traceable unit for that statement, each individually identifiable by which chunk it came from.

**Acceptance Scenarios**:

1. **Given** a statement processed into multiple chunks running concurrently, **When** normalization
   completes, **Then** every chunk's LLM call is visible as part of one traceable unit for that
   statement, not as unrelated, ungrouped calls.
2. **Given** a normalization run, **When** its LLM calls are inspected afterward, **Then** each one
   is individually identifiable by which statement and which chunk it belongs to.
3. **Given** the prompt template used for extraction changes, **When** a normalization run using the
   new template completes, **Then** its LLM calls are distinguishable from calls made under a
   previous template version.

---

### Edge Cases

- What happens when a statement has no discernible account number anywhere in its source content? →
  the account number field is absent/null, the same as today's masked-hint field's null behavior —
  not an error, not a guess (User Story 2, Scenario 2).
- What happens when a single transaction's content is large enough to exceed even the row-based
  portion limit on its own (e.g. an unusually long description or many additional facts)? → a
  fallback size safeguard still bounds portion size so this doesn't silently break extraction (User
  Story 4, Scenario 2).
- What happens when the configured concurrency limit exceeds what the model provider can actually
  sustain (rate limits)? → this is the same existing operator-tunable tradeoff as today; the feature
  doesn't introduce a new failure mode, an operator lowers the limit same as they can today.
- What happens to a statement that was already normalized under the previous output shape (list-form
  additional facts, masked account hint) if it's re-normalized after this change? → re-normalizing
  overwrites the previously stored result at its location with the new shape, consistent with the
  no-versioning behavior already established for this endpoint.
- What happens when a statement's source content includes a kind of entry the presentation-format
  change hasn't specifically accounted for? → it is still included in a plain, readable textual form
  rather than dropped, pending confirmation of the full set of source content kinds this must handle.
- What happens if the observability/tracing backend is unreachable while normalizing a statement? →
  normalization completes and returns its result exactly as if tracing were fully working; nothing
  about extraction success or failure depends on trace export succeeding (User Story 6, FR-014).
- What happens when one extraction portion exhausts its retries while other portions running
  alongside it have already succeeded? → the entire normalization request still fails as a whole; no
  partial result is returned, the same all-or-nothing behavior as today's sequential processing
  (FR-016).

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: System MUST represent any facts beyond the minimum documented shape — at both the
  transaction level and the statement level — as a key-value map in the result, not as a list of
  individual key/value entries.
- **FR-002**: System MUST extract and return the account number exactly as it appears in the source
  document (unmasked, unredacted) when it is present and determinable.
- **FR-003**: System MUST return each transaction's running balance and a canonicalized/normalized
  merchant name (distinct from the raw extracted merchant text) as dedicated fields, when
  determinable from the source content — not folded into the general facts collection from FR-001.
- **FR-004**: System MUST present a statement's source content to the extraction model in a form
  that preserves table structure without duplicating the same content across two different textual
  encodings of it.
- **FR-005**: System MUST be able to process more than one extraction portion of a statement at the
  same time, up to a configurable limit, rather than always exactly one at a time.
- **FR-006**: The concurrency limit from FR-005 MUST remain operator-configurable without requiring
  a code change, defaulting to the same conservative (fully sequential) behavior as today.
- **FR-007**: System MUST divide a statement's content into extraction portions primarily by
  estimated transaction count per portion, not by the raw character length of the source markup.
- **FR-008**: System MUST still bound the maximum size of any single extraction portion as a
  fallback safeguard, independent of the row-count-based limit in FR-007.
- **FR-009**: Changing how content is divided into portions (FR-007/FR-008) or how many portions
  run concurrently (FR-005/FR-006) MUST NOT change the final set of transactions extracted for a
  given statement.
- **FR-016**: System MUST preserve today's all-or-nothing failure behavior under concurrent
  processing: if any single extraction portion exhausts its retries, the entire normalization
  request MUST fail, exactly as under today's sequential processing — no partial result (from
  portions that succeeded before the failing one) is ever returned.
- **FR-010**: System MUST allow its extraction approach to be swapped or extended without changing
  the normalization endpoint's request or response contract.
- **FR-011**: Because the current normalized-result shape (list-form additional facts, masked
  account hint) is already relied upon by a deployed backend consumer, the output-shape change in
  FR-001/FR-002/FR-003 MUST be treated as a breaking contract change requiring a coordinated update
  on the backend's consuming side — not shipped as a silent, unannounced shape change the backend
  discovers at runtime.

### Observability Requirements

- **FR-012**: System MUST make every per-chunk LLM call made while normalizing one statement
  identifiable as belonging to that statement and to a specific chunk, without requiring
  hand-written instrumentation beyond what the extraction call site already sets.
- **FR-013**: System MUST NOT require moving prompt content out of its current version-controlled
  template form in order to satisfy FR-012 — prompt-version identification must be additive to the
  existing template-file-based approach, not a replacement for it.
- **FR-014**: System MUST continue to return a normalization result even when the
  observability/tracing backend is unreachable or slow — tracing failures MUST NOT affect
  extraction success, consistent with this service's existing fail-open observability behavior.
- **FR-015**: The concurrency change (User Story 3) MUST NOT fragment one statement's LLM calls into
  apparently-unrelated traces — related calls for one statement must remain identifiable as
  belonging together regardless of how many ran concurrently.

### Key Entities

- **Normalized transaction**: one extracted transaction entry; gains a real (unmasked) account
  number association, dedicated running-balance and normalized-merchant-name fields, and a
  key-value map for any remaining facts beyond the documented minimum shape, in place of today's
  list-of-pairs form.
- **Normalized statement result**: the overall per-statement result (bank name, account number,
  transaction list, statement-level facts); its facts collection changes from a list of pairs to a
  key-value map.
- **Extraction portion**: a right-sized slice of a statement's source content sent to the model in
  one extraction call; now sized primarily by estimated transaction count rather than raw source
  text length, with a fallback size ceiling.
- **Extraction strategy**: the swappable mechanism that turns a statement's source content into a
  normalized result; exactly one exists today, but the system must be able to accommodate more than
  one without changing the calling contract.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: For a statement whose source clearly states an account number, the returned account
  number exactly matches the source digits with no masking applied, across a representative sample
  of real statements.
- **SC-002**: Every additional fact returned for a statement or transaction is directly addressable
  by its key (no secondary list-scanning step needed) — true for 100% of returned facts.
- **SC-003**: Normalizing a statement of at least 3 pages / 40+ transactions (this service's
  existing real-world validation benchmark), with the concurrency limit raised above its default,
  completes at least twice as fast as the same statement processed fully sequentially.
- **SC-004**: A statement of at least 3 pages / 40+ transactions completes extraction with zero
  portions failing due to a truncated or incomplete model response, across repeated runs.
- **SC-005**: A statement's total extracted transaction count and per-transaction field values are
  unchanged (within existing tolerance) when compared before and after the portioning-strategy
  change, confirming the switch to transaction-count-based sizing doesn't regress correctness.
- **SC-006**: Introducing an additional extraction strategy requires no change to the normalization
  endpoint's request/response contract and no change to any other strategy's behavior.
- **SC-007**: For a statement processed as multiple concurrent chunks, 100% of its LLM calls are
  traceable back to that specific statement and chunk after the fact.
- **SC-008**: Observability/tracing backend failures (unreachable, slow) cause zero normalization
  request failures, across repeated runs.

## Assumptions

- The backend's own consumption logic for the normalized result was not directly available to
  confirm field-by-field; the alignment described here (FR-001, FR-002, FR-003) is based on the
  backend's own transaction/account data model as already read-only-mirrored by this service.
- Returning an unmasked account number does not introduce a new trust-boundary concern: the
  recipient (the backend) already owns the banking relationship and already holds an unmasked
  equivalent elsewhere; no new external/third-party recipient is introduced by this change.
- Because the backend already consumes today's output shape (FR-011), shipping FR-001/FR-002/FR-003
  requires coordinating a corresponding backend-side change; this is a cross-team dependency, not
  something this feature can complete unilaterally.
- The full set of source-content entry kinds this feature must present cleanly to the model will be
  confirmed separately before the presentation-format change (FR-004) is implemented; the
  requirements here describe the desired outcome, not an entry-by-entry mapping.
- The concurrency limit (FR-005/FR-006) remains a configurable value defaulting to today's
  conservative, fully-sequential behavior, so existing low-tier/free-tier deployments aren't put at
  greater rate-limit risk by default.
- This feature does not change the normalization endpoint's authentication, error-handling contract,
  or audit-logging behavior — those remain as already established for this endpoint.
- Re-normalizing a statement that was previously normalized under the old output shape simply
  overwrites the stored result at its existing location with the new shape; no dual-shape support or
  migration of previously-stored results is required.
- This service already has a global, auto-instrumented LLM tracing setup (the existing observability
  feature) that captures every LangChain/LangGraph call process-wide with zero call-site changes
  required. This feature's observability work (User Story 6) is about enriching those already-
  captured traces with normalization-specific business context (statement, chunk, prompt version)
  and confirming the concurrency redesign doesn't break how related calls are grouped — not about
  adding tracing capability that doesn't exist today.
- Prompt-version identification (FR-013) is expected to be satisfiable with a lightweight identifier
  (e.g. a content hash or an explicit version marker in the existing template file) rather than by
  adopting the tracing tool's own hosted prompt-management/versioning system — this repo's prompts
  were deliberately externalized to git-committed template files very recently, and re-centralizing
  them into a third-party-hosted store would reverse that decision without a stated need to.
- Whether concurrently-executed extraction branches (User Story 3) produce correctly grouped traces
  under Python's async execution model is something to be verified empirically once implemented,
  not assumed in advance.
- FR-002's real, unmasked account number will also be captured by this service's existing global
  auto-instrumentation into tracing telemetry. Today's telemetry redaction patterns (card/phone/
  email-shaped values) do not recognize bank account numbers, and Constitution Principle III
  requires unconditional minimization for any telemetry copy — this is a known, real gap. It is
  explicitly OUT OF SCOPE for this feature (2026-07-23 clarification) and is tracked as a separate,
  later follow-up rather than blocking this feature's delivery.
