# Feature Specification: LLM Observability with Langfuse

**Feature Branch**: `013-langfuse-observability`

**Created**: 2026-07-20

**Status**: Draft

**Input**: User description: "lets implement llm observability using langfuse, it should be selfhosted and run with the other compose services"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trace an end-to-end LLM request (Priority: P1)

An engineer investigating a bad chat response, a slow normalization run, or an unexpected cost spike needs to see the full chain of LLM calls behind a single request — every prompt, response, model, token count, latency, and how the calls nested inside one another.

**Why this priority**: Without end-to-end traces, every LLM-related bug or cost question requires reproducing the issue locally and adding temporary print statements. This is the core value the feature exists to deliver — everything else builds on it.

**Independent Test**: Trigger any LLM-backed operation (e.g. a chat message or a document normalization run), then open the observability tool and find a trace that shows the full sequence of LLM calls made for that operation, each with its prompt, response, and timing.

**Acceptance Scenarios**:

1. **Given** the observability stack is running alongside the other services, **When** a user sends a chat message that invokes one or more LLM agents, **Then** a trace appears in the observability tool showing each LLM call made while handling that message, in order, with inputs and outputs visible.
2. **Given** a multi-step pipeline (e.g. statement normalization) that calls the LLM more than once, **When** the pipeline runs, **Then** all of those calls appear grouped under a single trace representing that pipeline run, not as unrelated, disconnected entries.
3. **Given** an LLM call fails or times out, **When** the failure occurs, **Then** the trace records the failure (including any error detail available) rather than silently omitting that step.

---

### User Story 2 - Monitor cost and usage across the service (Priority: P2)

A team lead or engineer wants to understand how much LLM usage (token volume, request counts, estimated cost) different features of the service are generating over time, to spot regressions or unexpectedly expensive flows.

**Why this priority**: Cost/usage visibility is a major driver for adopting observability, but it depends on traces already being captured (User Story 1). It's the next most valuable capability once raw tracing works.

**Independent Test**: After a period of normal service usage, open the observability tool's usage view and confirm token counts and request volume are broken down in a way that can be attributed back to the feature/flow that generated them (e.g. chat vs. normalization vs. embedding).

**Acceptance Scenarios**:

1. **Given** traces have been recorded for multiple features (chat, normalization, planning, embeddings), **When** a user views the observability tool's dashboard, **Then** usage/cost figures can be filtered or grouped by the originating feature or flow.
2. **Given** a time range is selected, **When** the user views the dashboard, **Then** aggregate token and request counts for that range are shown.

---

### User Story 3 - Run the observability stack locally without external dependencies (Priority: P1)

A developer running the full service locally (via the existing multi-container setup) needs the option to start the observability tool alongside the other services with no separate signup, hosted account, or external network dependency required — without imposing its extra containers on every developer who doesn't need local tracing (e.g. because they point at a cloud-hosted Langfuse instead, or don't need tracing at all).

**Why this priority**: The explicit requirement is that self-hosting must be available as part of the existing local stack, opt-in — without this, the feature doesn't meet its stated purpose and traces would depend on an external third-party service, which is unacceptable for this deployment. It must not be the *only* option, and it must not be forced on developers who don't want it.

**Independent Test**: Start the full set of local services from a clean state with the observability tool's opt-in flag/profile enabled, and confirm it becomes available and ready to receive traces without any manual account creation or external API key for the observability tool itself. Separately, confirm that starting the stack *without* that flag brings up everything else with no trace of the observability tool's containers.

**Acceptance Scenarios**:

1. **Given** a developer starts all local services from scratch with the observability tool's local stack enabled, **When** startup completes, **Then** the observability tool is reachable and healthy without requiring a connection to a hosted, third-party version of the tool.
2. **Given** a developer starts all local services from scratch without enabling the observability tool's local stack, **When** startup completes, **Then** none of the observability tool's own containers are running, and the rest of the stack is unaffected.
3. **Given** the developer stops and restarts the local services (with the observability tool's local stack enabled), **When** the stack comes back up, **Then** previously recorded traces are still present (data persists across restarts).

---

### Edge Cases

- What happens when the observability service is down or unreachable at the time an LLM call is made? The LLM call MUST still complete and return a result to its caller — observability is best-effort and must never block or fail a user-facing request.
- How does the system handle very large prompts/responses (e.g. long document text sent for normalization)? They should still be captured, though the system may reasonably truncate extremely large payloads to protect storage and UI usability.
- What happens to trace data already recorded when the observability service restarts or the underlying stack is redeployed? Data MUST persist and remain queryable afterward.
- How are sensitive values (e.g. API keys, secrets accidentally present in prompts) handled? Credentials used to reach the observability service itself must not be logged in plaintext in the application's own logs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST capture a trace for every LLM call made by the service's features (chat agents, normalization, planning, embeddings, and any other LLM-backed flow), including at minimum: the prompt/input, the response/output, the model used, latency, and token usage where available.
- **FR-002**: The system MUST group related LLM calls that occur within a single logical operation (e.g. one chat turn, one normalization run) into a single trace, preserving the order and nesting of calls.
- **FR-003**: The observability tool MUST support running self-hosted, as part of the same local multi-service environment as the rest of the application (started and stopped together via the same compose invocation), with no dependency on an external hosted version of the tool. This local stack MUST be optional — off by default — so environments that don't need it (e.g. ones pointing at a cloud-hosted instance instead) aren't forced to run its extra containers.
- **FR-004**: Trace data MUST persist across restarts of the observability service and the surrounding stack.
- **FR-005**: The system MUST continue to serve LLM-backed requests normally even if the observability service is unavailable, slow, or unreachable — tracing failures MUST NOT surface as user-facing errors or block responses.
- **FR-006**: The observability tool MUST provide a way to view usage/cost metrics (token counts, request counts) attributable to the feature or flow that generated them.
- **FR-007**: Access to the observability tool's UI and data MUST be restricted to authorized users (not publicly reachable without authentication).
- **FR-008**: The system MUST record failed or errored LLM calls in traces rather than omitting them.
- **FR-009**: Configuration required to connect the application to the observability tool (endpoint, credentials) MUST be supplied via the same environment-based configuration mechanism already used for other service settings, and MUST NOT be committed to source control.

### Key Entities

- **Trace**: Represents one logical operation (e.g. a chat turn, a normalization run) that may involve one or more LLM calls; has a start/end time, an overall status, and an association with the feature/flow that initiated it.
- **Observation (LLM call/span)**: A single step within a trace — an LLM call, a sub-step of a pipeline, or a tool invocation — with its own input, output, timing, and (for LLM calls) token usage and model identity.
- **Usage metric**: Aggregated token and request counts derived from traces, attributable to a feature/flow and a time period.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any LLM-backed request made to the service, an engineer can find its complete trace in the observability tool within 10 seconds of the request completing.
- **SC-002**: 100% of LLM calls made by the service's existing features are captured as trace data, with no feature silently excluded.
- **SC-003**: When explicitly enabled, the observability stack starts successfully together with the rest of the local environment in the same single startup action, with zero additional manual setup steps beyond configuration already documented for other services and the one opt-in flag used to enable it. When not enabled, none of its containers start and the rest of the environment is unaffected.
- **SC-004**: If the observability service is stopped entirely, LLM-backed requests to the application continue to succeed with no measurable increase in error rate.
- **SC-005**: An engineer can determine total LLM token usage for a given feature over a given time range from the observability tool's dashboard without needing to query application logs or databases directly.

## Assumptions

- "Self-hosted, running with the other compose services" means the observability tool's own services (application, database, and any supporting services it requires) are added to the existing local multi-service definitions and are started/stopped as part of the same workflow already used for the rest of the stack — not deployed separately or hosted by a third party. This local stack is opt-in (a dedicated compose profile, off by default): the requirement is that self-hosting be available with no additional manual setup when chosen, not that it always runs. A developer who instead wants to point at a cloud-hosted Langfuse simply sets its endpoint/keys and never enables the local profile.
- The service's existing LLM/agent framework supports integration with the chosen observability tool through a standard, low-friction integration path (callback/handler or SDK wrapper) rather than requiring a rewrite of LLM call sites.
- Observability is additive: it captures data about existing LLM calls without changing their behavior, inputs, outputs, or latency in any way that's noticeable to end users.
- Non-production (local/dev) environments are the primary initial target; the same self-hosted setup is assumed to be reusable for other environments later, but multi-environment deployment topology is out of scope for this feature.
- Trace and usage data retention policy is not explicitly specified; the tool's own reasonable defaults are assumed acceptable until a specific retention requirement is raised.
- User authentication for the observability tool's own UI uses a simple built-in mechanism (e.g. a single admin account or shared credentials) appropriate for an internal team tool, rather than integration with the application's own end-user authentication.
