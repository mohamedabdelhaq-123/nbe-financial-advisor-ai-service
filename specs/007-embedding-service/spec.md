# Feature Specification: Text Embedding Service

**Feature Branch**: `007-embedding-service`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "I want to implement embedding in our application, we would get_embedding_model function imported from embedding package as core service, it will need configs, for mocking, it should be internal, meaning get_embedding_model returns  a mock model, so behaviour across the app stays consistent, again avoid hand rolled implementation, if langchain provide embedding utilities use it. alongside the core service, we want an embedding feature, this feature will expose endpoints for backend to embed its texts if it wants. It should matches OpenAI's embedding's API. if there is a neat and clean way that requires minimum hand rolled implementations, use it.  Also if there is a way to mock the embedding model provided from the libraries, use it."

## Clarifications

### Session 2026-07-13

- Q: Per Constitution Principle III, PII must be minimized/redacted before crossing a trust boundary, explicitly including inclusion in LLM prompts and logs. Text sent to an external embedding provider crosses that same boundary. Should the embeddings feature enforce any PII handling on submitted text, or is that the caller's (backend's) responsibility? → A: Caller's (backend's) responsibility — this service embeds exactly the text it is given, with no server-side PII detection or redaction.
- Q: Constitution Principle III requires every "privileged action" to be recorded to this service's audit log. Should each call to the embeddings endpoint be recorded as an audit log entry? → A: No — embedding text is a stateless transformation, not a privileged action over financial records; no audit log entry is written per call.
- Q: Should the system retry automatically before failing when the real embedding provider is unreachable or errors, or fail immediately on the first error? → A: Fail immediately — no automatic retries; the error is surfaced to the caller right away, matching the existing chat/LLM call pattern.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Internal features obtain embeddings through one shared capability (Priority: P1)

Any feature inside this AI service that needs to turn text into vectors (for example, a future semantic-search or retrieval capability) can request an embedding model through a single, shared entry point instead of each feature wiring its own provider calls or its own test/mock logic.

**Why this priority**: This is the foundation every other embedding use case builds on. Without a single consistent way to obtain an embedding model, each feature would duplicate provider wiring and drift out of sync in how it handles mock vs. real behavior — exactly the kind of inconsistency this feature exists to prevent.

**Independent Test**: Can be fully tested by having a feature request an embedding model and submit sample text, and verifying it receives vectors — with identical calling code whether the service is running in mock or real mode.

**Acceptance Scenarios**:

1. **Given** the service is configured in mock mode, **When** an internal feature requests the shared embedding capability and submits text, **Then** it receives vectors without any feature-specific mock-handling code.
2. **Given** the service is configured in real mode with a valid provider configuration, **When** an internal feature requests the shared embedding capability and submits text, **Then** it receives vectors produced by the configured provider, using the same calling code as in mock mode.
3. **Given** two different internal features both request the shared embedding capability, **When** both are run under the same configuration, **Then** both observe identical mock/real behavior (no feature can end up in a different mode than the rest of the service).

---

### User Story 2 - Backend submits text and receives embeddings over an API (Priority: P1)

The backend team can call an endpoint on this service, submit one or more pieces of text, and receive back their embeddings in a request/response shape that matches the OpenAI embeddings API, so existing OpenAI-compatible client tooling can be pointed at this service with no bespoke integration work.

**Why this priority**: This is the externally visible capability the backend depends on — without it, this feature delivers no value outside the AI service itself.

**Independent Test**: Can be fully tested by sending an authenticated request with one or more text inputs to the embeddings endpoint and verifying the response contains one vector per input, structured in the OpenAI embeddings response shape.

**Acceptance Scenarios**:

1. **Given** a valid authenticated request with a single text input, **When** the backend calls the embeddings endpoint, **Then** the response contains exactly one embedding vector for that text, in the OpenAI embeddings response shape.
2. **Given** a valid authenticated request with multiple text inputs, **When** the backend calls the embeddings endpoint, **Then** the response contains one embedding vector per input text, in the same order as submitted.
3. **Given** an unauthenticated request, **When** the backend (or anyone) calls the embeddings endpoint, **Then** the request is rejected and no embeddings are computed.

---

### User Story 3 - Consistent, deterministic behavior in test and CI environments (Priority: P2)

Developers and CI pipelines running the service in mock mode get deterministic embeddings — the same input text always produces the same vector — so tests that assert on embedding output stay stable and repeatable without contacting any external provider.

**Why this priority**: This unlocks fast, offline, repeatable automated testing of anything built on top of embeddings, but the service is still independently useful (per User Stories 1 and 2) without this determinism guarantee being spelled out explicitly.

**Independent Test**: Can be fully tested by requesting an embedding for the same text twice in mock mode and verifying both vectors are identical, with no network access required.

**Acceptance Scenarios**:

1. **Given** mock mode is enabled, **When** the same text is embedded twice, **Then** both calls return the identical vector.
2. **Given** mock mode is enabled, **When** two different texts are embedded, **Then** they return different vectors.

---

### Edge Cases

- What happens when the embeddings endpoint receives an empty text list, or a list containing only empty/whitespace strings?
- What happens when the configured external embedding provider is unreachable or returns an error in real mode?
- What happens when a submitted text exceeds the configured provider's length/token limit?
- How does the system behave if mock mode is toggled between two calls within the same test run — do previously mocked vectors change, or does each call reflect the mode active at call time?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a single shared entry point that any internal feature can use to obtain a ready-to-use embedding capability, without each feature implementing its own provider wiring.
- **FR-002**: The shared embedding entry point MUST support a configuration-driven mock mode; when enabled, it MUST return a mock embedding capability so calling code does not need to branch on mode itself.
- **FR-003**: In real mode, embeddings MUST be produced by a configured external embedding provider/model rather than by custom hand-built vector generation logic.
- **FR-004**: In mock mode, embeddings MUST be deterministic: the same input text, under the same configuration, MUST always produce the same vector.
- **FR-005**: The system MUST expose an HTTP endpoint that accepts one or more text inputs from the backend and returns their embeddings.
- **FR-006**: The embeddings endpoint's request and response structure MUST match OpenAI's embeddings API contract, so OpenAI-compatible client tooling can integrate against it unmodified.
- **FR-007**: The embeddings endpoint MUST require the same authenticated, service-to-service access already required by this service's other backend-facing endpoints, and MUST reject unauthenticated requests.
- **FR-008**: The system MUST reject requests that contain no usable text input (empty list, or only empty/whitespace strings) with a clear, actionable error rather than returning empty or malformed results.
- **FR-009**: The system MUST support embedding multiple text inputs in a single request and return their embeddings in the same order as submitted.
- **FR-010**: The embedding provider/model configuration (which provider, which model, mock mode on/off) MUST be centrally managed so it can change without modifying the code at any call site.
- **FR-011**: When the real embedding provider is unreachable or returns an error, the system MUST surface a clear failure to the caller immediately, with no automatic retries, rather than returning empty, zero, or otherwise silently invalid vectors.
- **FR-012**: The system MUST embed submitted text as-is, without performing its own PII detection or redaction; responsibility for what text is safe to submit rests with the calling backend.
- **FR-013**: Embedding requests are treated as a stateless transformation and are not required to be recorded in the audit log (unlike privileged actions over financial records).
- **FR-014**: The system MUST allow a caller to request a non-default output vector size for a given embedding request; omitting it MUST fall back to a centrally configured default size.

### Key Entities

- **Embedding Request**: One or more input texts (and the implicit or explicit embedding model to use) submitted for embedding.
- **Embedding Response**: The resulting list of embedding vectors, one per input text, returned in the same order as the request, structured to match the OpenAI embeddings response contract (including any accompanying usage/metadata fields that contract defines).
- **Embedding Model Configuration**: The centrally managed settings that determine which provider/model produces embeddings in real mode, and whether mock mode is active.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer adding a new internal feature that needs embeddings can do so using a single shared call, with zero feature-specific mock-handling code, and zero hand-rolled vector-generation logic.
- **SC-002**: Switching the whole service between mock and real embedding behavior requires only a configuration change — no code changes in any feature that consumes embeddings.
- **SC-003**: The backend team can submit a batch of texts in one request and receive one matching embedding per text, in a response shape consumable by existing OpenAI-embeddings-compatible client code, with no custom parsing logic needed on their side.
- **SC-004**: 100% of embedding requests with invalid input (empty or all-blank text list) receive a clear rejection instead of a malformed, empty, or silently incorrect response.
- **SC-005**: In mock mode, embedding the same text repeatedly returns the identical vector 100% of the time, enabling deterministic automated tests with no external network dependency.

## Assumptions

- The embedding provider is accessed the same way this service already accesses its chat/completions provider (a configurable, OpenAI-compatible provider), so no new provider-integration pattern is introduced.
- A single embedding model/provider configuration is active at a time; callers do not select a different *embedding model or provider* per individual request (mirrors this service's existing single-configured-model pattern for chat completions). Output vector *size* is the one exception (FR-014): a caller may request a non-default size for a given call, independent of which model/provider is configured.
- The embeddings endpoint is for internal, service-to-service use by the backend only (not exposed to end users directly), authenticated the same way this service's existing backend-facing endpoints are.
- No additional artificial limits (batch size, text length) are imposed beyond what the configured embedding provider itself enforces.
- Embedding vectors and requests are not persisted by this feature; storage/indexing of embeddings (e.g. for retrieval) is out of scope and left to whichever feature consumes this capability.
