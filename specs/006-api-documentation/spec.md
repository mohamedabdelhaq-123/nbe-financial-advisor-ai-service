# Feature Specification: API Documentation

**Feature Branch**: `[006-api-documentation]`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "we need to have token based authentication" (superseded during clarification — see Assumptions; the confirmed scope is richer OpenAPI/Swagger documentation for the internal API)

## Clarifications

### Session 2026-07-13

- Q: FR-006 requires documentation gaps (missing description/example) to be "identifiable rather than shipping silently" — who/what identifies them? → A: Manual PR review only — no automated check; reviewers are relied on to catch missing docs during code review.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Integrate against a documented endpoint without reading source (Priority: P1)

A Django backend developer who needs to call an `/internal/*` endpoint (chat, analytics, plan, ingestion, or recommendations) opens the service's interactive documentation and finds everything needed to make a correct call: what the endpoint does, what to send, what comes back on success, and what comes back on failure — without opening the AI service's source code.

**Why this priority**: This is the entire value of the feature. Without accurate, complete documentation per endpoint, nothing else in the feature matters.

**Independent Test**: Can be fully tested by opening the documentation UI, picking any one `/internal/*` endpoint, and confirming a developer can construct a valid request/response expectation using only what's shown — no source reading required.

**Acceptance Scenarios**:

1. **Given** the documentation UI is open, **When** a developer selects any `/internal/*` endpoint, **Then** they see a plain-language description of its purpose, its required request fields/types, and its success response shape.
2. **Given** a developer is viewing an endpoint's documentation, **When** they look for failure behavior, **Then** they see every error status code the endpoint can return (e.g. unauthorized, validation failure, server error) with the shape of each error response.
3. **Given** a developer is viewing an endpoint's documentation, **When** they look for a usage sample, **Then** they find at least one representative example request and matching example response.

---

### User Story 2 - Documentation stays truthful as the API evolves (Priority: P2)

A developer adding or changing an `/internal/*` endpoint wants the documentation to reflect that change automatically (or to be flagged when it doesn't), so the documentation never silently drifts out of sync with what the API actually does.

**Why this priority**: Valuable for long-term trust in the documentation, but the feature still delivers its core value (P1) on day one even before a drift-prevention mechanism exists.

**Independent Test**: Can be fully tested by adding a new field to an existing endpoint's request/response model and confirming the documentation reflects the change without any separate manual documentation-editing step.

**Acceptance Scenarios**:

1. **Given** a request or response model gains, loses, or changes a field, **When** the documentation is viewed afterward, **Then** it reflects the current shape without a developer having hand-edited a separate documentation artifact.
2. **Given** a new `/internal/*` endpoint is added without a description or example, **When** a reviewer reads the rendered documentation during PR review, **Then** the gap is visibly identifiable (e.g. an empty or generic entry) rather than looking indistinguishable from a fully documented endpoint.

---

### Edge Cases

- What happens when a streaming (Server-Sent Events) endpoint is viewed in the documentation UI, given that "try it out"-style interactive execution does not naturally represent a stream of events? The documentation must still describe the event/stream shape a caller should expect.
- What happens when an endpoint's underlying model has a field with no description authored? It renders as an empty/generic entry a PR reviewer can spot, rather than being indistinguishable from a documented field; there is no automated check for this.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide interactive, browsable documentation covering every `/internal/*` endpoint's purpose, request shape, and success response shape.
- **FR-002**: The system MUST document, for every `/internal/*` endpoint, every error status code it can return and the shape of each corresponding error response.
- **FR-003**: The system MUST include at least one representative example request and one representative example response for every `/internal/*` endpoint.
- **FR-004**: The system MUST describe streaming (Server-Sent Events) endpoint behavior in the documentation in a way that communicates the event/stream shape, even though such an endpoint cannot be fully exercised through a standard "try it out" request/response form.
- **FR-005**: The documentation MUST be derived from the same request/response definitions the API uses to validate and serialize traffic, so that a change to those definitions is reflected in the documentation without a separate manual editing step.
- **FR-006**: A missing description or example on an `/internal/*` endpoint, field, or error case MUST be catchable by a reviewer reading the documentation during PR review; this is a manual review responsibility, not an automated build check.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of `/internal/*` endpoints have a documented purpose description, request/response shape, and at least one example request and response.
- **SC-002**: 100% of `/internal/*` endpoints list every error status code they can return, with the shape of each error response.
- **SC-003**: A developer unfamiliar with the codebase can determine the correct request/response shape for any given `/internal/*` endpoint using only the documentation, in under 5 minutes per endpoint.

## Assumptions

- The delivery mechanism is the service's existing auto-generated interactive documentation (OpenAPI schema, Swagger UI, and ReDoc), enriched with descriptions, examples, and error-response detail — not a separately authored documentation site or standalone written guide.
- The documentation audience is solely the Django backend integration team; this is an internal-only service never exposed to the frontend, so no end-user-facing documentation is in scope.
- The documentation UI (`/docs`, `/redoc`) and the underlying schema (`/openapi.json`) keep their existing access posture — this feature does not change who can reach them; it only enriches what they show. Authentication of the API itself is out of scope for this feature (see below).
- This feature originated from a request for "token-based authentication," which was found to already exist in full (a shared-secret Bearer token enforced on every `/internal/*` route, tested in `tests/features/test_auth_matrix.py`); the confirmed scope for this spec is documenting the API — including describing that existing authentication requirement in each endpoint's docs — rather than building new authentication or changing who can view the documentation.
