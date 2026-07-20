# Phase 0 Research: Structured Logging Setup

No `[NEEDS CLARIFICATION]` markers remain in the Technical Context — both
open questions from spec authoring (correlation-ID sourcing, debug-mode raw
content) were resolved with the user before `plan` started. This document
records the technology and pattern decisions needed to execute the plan.

## Decision: Structured logging library

**Decision**: Use `structlog`, configured to render every log line as one
JSON object, with its stdlib-`logging` integration (`ProcessorFormatter`) so
third-party libraries that log through the standard `logging` module (e.g.
`uvicorn`, `sqlalchemy`) are captured in the same structured format.

**Rationale**: Principle VIII requires preferring a maintained library
primitive over a hand-rolled implementation. `structlog` is the de facto
standard for structured logging in Python: it provides JSON rendering,
contextvars-based value binding (needed for correlation IDs propagating
through `asyncio.gather` fan-out, per FR-004), and a stdlib-`logging` bridge
in one well-maintained package, replacing what would otherwise be a
hand-rolled `logging.Formatter` subclass plus a manual contextvar-to-record
bridge.

**Alternatives considered**:
- *Hand-rolled `logging.Formatter` subclass emitting JSON*: rejected —
  duplicates what `structlog` already solves, and still needs a separate,
  hand-written mechanism for correlation-ID propagation across async tasks.
- *`python-json-logger`*: rejected — solves only JSON formatting, not
  context binding; would still need a hand-rolled contextvar bridge for
  FR-004, reintroducing the problem Principle VIII asks to avoid.
- *stdlib `logging` with `extra=` dict passed at every call site*: rejected
  — pushes correlation-ID inclusion onto every individual call site instead
  of binding it once per request, which is error-prone (easy to forget) and
  directly risks violating FR-004's "every log entry" requirement.

## Decision: Correlation ID propagation mechanism

**Decision**: A FastAPI middleware generates one UUID4 per inbound request,
binds it via `structlog.contextvars.bind_contextvars(correlation_id=...)` at
the start of the request, and clears it via `clear_contextvars()` when the
request finishes (in a `finally`). Because Python `contextvars` are copied
into child tasks at creation time, IDs bound this way propagate automatically
into the LangGraph/`asyncio.gather` fan-out used by chat sub-agents and
statement normalization, with no changes needed at those call sites.

**Rationale**: Matches the user's resolved decision (self-generated IDs, no
incoming-header dependency on Django). Contextvar binding satisfies FR-004
("every log entry produced while handling a given request") without
threading an explicit parameter through every function call — consistent
with Principle VIII's preference for the library's native mechanism
(`structlog.contextvars`) over a hand-rolled propagation scheme.

**Alternatives considered**:
- *Explicit `correlation_id` parameter threaded through every service/agent
  call*: rejected — high blast radius across every existing feature slice's
  function signatures for no behavioral benefit over contextvar binding.
- *Correlation ID stored only on `request.state`*: rejected — not visible to
  code running outside the FastAPI request-handling path (e.g. a log line
  emitted from deep inside a LangGraph node), which would violate FR-004.

## Decision: Redaction / preventing PII, financial data, and secrets in logs

**Decision**: Two layers: (1) log *calls* only ever pass structured
key/value fields and short human-readable messages — never a raw ORM model,
DTO, or backend-mirror row object — enforced by code review and a lint-level
convention documented at the `get_logger()` call site; (2) a `structlog`
processor denylists a fixed set of field names that must never appear
(`api_key`, `token`, `password`, `authorization`, `*_secret`, `*_key`) and
replaces their values with `"[REDACTED]"` if a call site ever passes one
accidentally, as a defense-in-depth backstop rather than the primary
mechanism.

**Rationale**: Mirrors Principle III's existing approach for DTOs/prompts —
minimization is enforced at the egress boundary (here, the log-call
boundary), not by trusting every call site to remember. The processor
backstop matches FR-005's "MUST NEVER" wording with an automated guarantee
rather than relying solely on developer discipline, addressing the edge case
in the spec about a developer accidentally logging a raw object.

**Alternatives considered**:
- *Rely solely on code review / convention, no automated backstop*: rejected
  — a single missed review comment would violate FR-005 with no safety net,
  unacceptable for regulated financial data.
- *Allowlist-only field validation (reject anything not pre-declared)*:
  rejected as the primary mechanism — too rigid for free-form human-readable
  messages and would slow ordinary development; kept the lighter denylist
  backstop instead, consistent with how Principle III already scopes
  minimization to known-sensitive fields at the DTO layer rather than
  requiring a full schema for every log line.

## Decision: Debug-mode raw content logging (FR-011)

**Decision**: A single settings flag, `log_debug_include_raw_content: bool =
False` (fail-fast validated like other `Settings` fields), gates whether the
LLM-calling and DB-query code paths are permitted to pass raw
prompt/completion/query fields to the logger at `DEBUG` severity. When
`False` (the default), those call sites pass only metadata (token counts,
latency, model name, row counts) regardless of configured log level. A
startup-time `WARNING`-level log line is emitted once if the flag is `True`,
so enabling it is never silent.

**Rationale**: Matches the user's resolved decision (opt-in only, default
off, no production-safe default path to enabling it — "production-safe
default configuration" is satisfied because the shipped default is `False`
and nothing in normal deployment configuration turns it on).

**Alternatives considered**:
- *Tie raw content solely to `log_level=DEBUG`*: rejected — conflates
  "verbose diagnostic logging" with "logging regulated content," which the
  user explicitly wanted separated (an engineer could reasonably want DEBUG
  verbosity without raw prompt/query content ever appearing).

## Decision: Access logging (FR-007) and uvicorn's default access log

**Decision**: Disable uvicorn's built-in access log (`--no-access-log` /
`access_log=False` at the ASGI server config) and replace it with the same
middleware that binds the correlation ID, which logs one structured line per
completed request (method, path, status, duration) after `call_next`
returns, in a `try`/`finally` so it still fires on unhandled exceptions.

**Rationale**: Running both would produce two differently-formatted access
log lines per request, violating FR-001's "consistent... format" and
SC-002's "100% of log lines match the defined structured format."

**Alternatives considered**:
- *Keep uvicorn's default access log alongside the new structured one*:
  rejected — directly conflicts with FR-001/SC-002.
- *Reconfigure uvicorn's own logger to also emit structlog-formatted JSON*:
  rejected as unnecessary complexity — the middleware already produces a
  richer, correlation-ID-tagged line; there is nothing uvicorn's separate
  access logger would add.
