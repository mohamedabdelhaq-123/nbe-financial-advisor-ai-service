# Feature Specification: Structured Logging Setup

**Feature Branch**: `012-structured-logging-setup`

**Created**: 2026-07-20

**Status**: Draft

**Input**: User description: "lets have a proper logging setup for the project"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Diagnose a production error from logs alone (Priority: P1)

An on-call engineer is alerted that requests are failing. They open the
service's log output and, without redeploying or reproducing the issue
locally, find a clear entry showing the failure: when it happened, which
feature it came from, what went wrong, and the full error detail needed to
understand root cause.

**Why this priority**: This is the core value of "proper logging" — turning
an opaque production failure into something diagnosable in minutes. Without
this, every other logging capability is secondary.

**Independent Test**: Trigger an unhandled error in any feature slice and
verify a single log entry appears with severity, timestamp, originating
module, error message, and stack trace — readable without any other tooling.

**Acceptance Scenarios**:

1. **Given** the service is running, **When** an unhandled exception occurs
   while handling a request, **Then** a log entry is emitted at error
   severity containing the exception type, message, and stack trace, and the
   request still returns a response instead of crashing the process.
2. **Given** a request completes successfully, **When** it finishes, **Then**
   a log entry records the request method, path, response status, and
   duration, without including the request or response body.

---

### User Story 2 - Trace one request across multiple feature slices (Priority: P2)

A developer is debugging a chat request that fans out from the Maestro
orchestrator into sub-agents, or an ingestion job that fans out into several
normalization chunks. They need every log line produced while handling that
one request or job to be identifiable as belonging together, so they can
reconstruct the full sequence of what happened.

**Why this priority**: Multi-step, fan-out processing is central to this
service's architecture (Maestro + sub-agents, chunked normalization). Without
a shared identifier, related log lines are indistinguishable from unrelated
concurrent traffic, making non-trivial issues effectively undiagnosable.

**Independent Test**: Issue a request that triggers multi-step processing
(e.g. a chat turn or a statement normalization run) and verify every log
line produced while handling it carries the same correlation identifier,
distinct from concurrent unrelated requests.

**Acceptance Scenarios**:

1. **Given** two requests are being handled concurrently, **When** their log
   entries are inspected, **Then** each request's entries share one
   identifier and no entry from one request carries the other's identifier.
2. **Given** a single request triggers work across multiple feature slices,
   **When** that work completes, **Then** all resulting log entries carry the
   same identifier as the originating request.

---

### User Story 3 - Confirm logs never leak regulated data (Priority: P3)

A security or compliance reviewer inspects a sample of production log output
to confirm that personally identifiable information, financial figures, and
secret values (API keys, tokens, credentials) never appear in logs, matching
the same data-minimization guarantee already required for LLM prompts and
DTOs leaving the service.

**Why this priority**: This service processes regulated financial data.
Logs are a trust-boundary crossing point like any other; the diagnostic value
of logging is only acceptable if it doesn't become a second, unaudited path
for regulated data to leak out.

**Independent Test**: Exercise every feature slice's logging output (normal
operation and error paths) and confirm no entry contains PII, financial
account data, or secret values, including when verbose/debug logging is
enabled.

**Acceptance Scenarios**:

1. **Given** debug-level logging is left at its default (disabled), **When**
   any request is processed, **Then** no log entry contains raw LLM prompt
   or completion text, or raw database query parameter values.
2. **Given** any log entry is produced anywhere in the service, **When** it
   is inspected, **Then** it contains no secret values (API keys, bearer
   tokens, database credentials) regardless of configured verbosity.

---

### Edge Cases

- What happens when the logging system itself fails (e.g. a malformed log
  call, an unavailable output stream)? The failure must not crash the
  request being handled or the process.
- How does the system behave under a high-volume, tight-loop code path (e.g.
  per-chunk normalization progress) at default verbosity, versus with debug
  logging enabled?
- What happens to log output produced before application configuration has
  finished validating at startup — is it still emitted in the same
  consistent format as post-startup logs?
- How are log entries correlated for asynchronous, multi-tick background
  work (e.g. a LangGraph run spanning several ticks) where there is no
  single synchronous call stack?
- What happens if a developer writes a log call that accidentally includes a
  raw object containing PII or a secret — does the logging setup make this
  an easy mistake to make, or does it push toward safe usage by construction?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST emit all application log output in a consistent,
  structured, machine-parseable format across every feature slice and every
  runtime environment.
- **FR-002**: System MUST support a configurable minimum log severity
  threshold, set via environment configuration and validated at startup
  (invalid values MUST fail fast rather than silently falling back).
- **FR-003**: Every log entry MUST include, at minimum: a timestamp, a
  severity level, the originating feature/module, and a human-readable
  message.
- **FR-004**: System MUST attach a correlation identifier to every log entry
  produced while handling a given inbound request or background job, so all
  entries for that unit of work can be grouped together. This identifier is
  generated by the AI service itself for each request/job; it is not sourced
  from an incoming header.
- **FR-005**: System MUST NEVER include personally identifiable information,
  financial figures/account data, or secret values (API keys, bearer tokens,
  database credentials) in any log entry, at any configured verbosity level.
- **FR-006**: System MUST log every unhandled exception at error severity
  (or higher), including exception type, message, and stack trace, without
  the logging itself interrupting the request/response cycle.
- **FR-007**: System MUST log each inbound request handled by the service
  (method, path, response status, duration) at a level suitable for routine
  operational visibility, excluding request and response bodies.
- **FR-008**: System MUST provide a single, consistent way for any feature
  slice to obtain a logger, replacing today's ad hoc per-file setup, so log
  behavior and format stay uniform as the codebase grows.
- **FR-009**: Liveness and readiness probe handling MUST NOT be blocked or
  delayed by logging, consistent with those endpoints making no external
  calls.
- **FR-010**: Log output MUST be written to a destination the container
  platform can collect without additional service-level configuration
  (i.e. standard output).
- **FR-011**: System MUST support an explicit, opt-in debug mode that, only
  while enabled, may include raw LLM prompt/completion text and raw database
  query content in logs for local troubleshooting. This mode MUST default to
  disabled, and enabling it MUST NOT be possible via a production-safe
  default configuration (i.e. it requires a deliberate, explicit override).

### Key Entities

- **Log Entry**: A single emitted record of something the system did or
  observed. Carries a timestamp, severity level, originating
  feature/module, human-readable message, correlation identifier, and
  (when applicable) structured exception detail. Never carries PII,
  financial data, or secret values outside the explicit opt-in debug mode
  described in FR-011, which itself excludes secrets unconditionally.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Given a correlation identifier from any single failed request,
  an engineer can retrieve every log entry produced while handling that
  request using only that identifier, with no manual timestamp
  cross-referencing.
- **SC-002**: 100% of log lines emitted by the service match the defined
  structured format and can be parsed without error by a generic log
  processor.
- **SC-003**: A review of a representative sample of log output across all
  feature slices, at both default and debug verbosity, finds zero instances
  of PII, financial account data, or secret values (secrets: zero instances
  at any verbosity; raw prompt/query content: zero instances outside the
  explicit opt-in debug mode).
- **SC-004**: Changing the configured log verbosity requires only an
  environment configuration change and a restart — no code change.
- **SC-005**: Every feature slice's log output is indistinguishable in
  format and structure from any other slice's, confirming a single
  consistent logging setup is in use service-wide.

## Assumptions

- Shipping logs to an external aggregation/search system (e.g. a log
  platform or SIEM) is out of scope for this feature; this feature
  guarantees structured stdout output that such a system could consume,
  but wiring one up is a separate, later concern.
- Log retention and storage duration are managed by the surrounding
  container/orchestration platform, not by this service.
- This feature is distinct from and does not change the existing audit-trail
  feature, which records privileged actions to the service's own database
  for compliance purposes; this feature covers operational/diagnostic
  logging only.
- The default log severity threshold in the absence of explicit
  configuration is informational (routine operational events visible;
  fine-grained diagnostic detail suppressed).
- Because the Django backend is this service's only caller and no shared
  request-ID contract exists between them today, correlation identifiers are
  generated independently per request/job (per FR-004) rather than sourced
  from Django; joining an AI-service trace to the matching Django-side
  request is out of scope for this feature.
