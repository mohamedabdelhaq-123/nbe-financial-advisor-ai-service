# Feature Specification: Consistent, Fault-Tolerant Environment Configuration

**Feature Branch**: `014-env-config-consistency`

**Created**: 2026-07-21

**Status**: Draft

**Input**: User description: "Consistent, fault-tolerant environment/config setup for the ai-service. Scope agreed in prior discussion (not yet implemented): (1) remove redundant/conflicting environment defaults from the Docker Compose service definition so the environment file is the single source of truth for the ai-service's own configuration; (2) group related configuration settings together by domain (LLM, embeddings, own database, backend database, storage, document processing, observability, logging); (3) make configuration validation independently testable rather than tied to a process-wide singleton; (4) ensure every required configuration group fails startup immediately and clearly when left unset or at a placeholder value, including the service's own database credentials, which currently has no such check; (5) decide whether backend database access is required in every real deployment or remains legitimately optional, and validate accordingly; (6) ensure credential-shaped configuration values can never leak in plaintext through logs or error output; (7) keep the example environment template complete and in sync with what's actually required to run the service."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fail fast with an actionable message on misconfiguration (Priority: P1)

A developer or operator starts the ai-service (locally, in CI, or in a deployment) with an environment file that is missing a required value, or that still has a placeholder/example value left in place for something that must be real. The service refuses to start and reports exactly which configuration is missing or invalid, and what to do about it — for every required configuration group, not just some of them.

**Why this priority**: This is the core reliability property the whole effort is about. Today, some required configuration groups (e.g. the service's own database credentials) have no such check, so a missing or placeholder value is discovered later, as a confusing runtime failure, rather than at startup.

**Independent Test**: Start the service with each required configuration group in turn left unset or at its placeholder value; confirm the service fails immediately at startup with a message naming the specific missing/placeholder values, for every group.

**Acceptance Scenarios**:

1. **Given** a required configuration value is missing from the environment, **When** the service starts, **Then** startup fails immediately with a message identifying that value by name.
2. **Given** a required configuration value is still set to its documented placeholder, **When** the service starts, **Then** startup fails immediately, distinguishing "left at placeholder" from "not set" where that distinction is meaningful.
3. **Given** all required configuration groups are correctly set, **When** the service starts, **Then** startup succeeds with no configuration-related errors.

---

### User Story 2 - One source of truth for configuration values (Priority: P1)

A developer configuring the service changes a value in the environment file and expects that value to take effect. Today, the container-orchestration layer independently declares default values for the same settings, and those declared defaults can silently override what's in the environment file — so a developer's change appears to have no effect.

**Why this priority**: Silent overrides are a direct source of lost debugging time and erode trust in the environment file as the place to make changes — this was the triggering problem for the whole effort.

**Independent Test**: Set a non-default value for a given setting in the environment file, start the service via the standard local workflow, and confirm the running service actually uses that value rather than a conflicting default declared elsewhere.

**Acceptance Scenarios**:

1. **Given** a setting has a value in the environment file, **When** the service starts through the standard local workflow, **Then** the running service uses the environment file's value.
2. **Given** a setting is absent from the environment file, **When** the service starts, **Then** the running service falls back to exactly one clearly-defined default, not one of several possibly-conflicting defaults.
3. **Given** a deterministic, isolated test/smoke-test run that must not depend on whatever is in a developer's local environment file, **When** that run starts the service, **Then** its own explicit overrides take effect regardless of the environment file's contents.

---

### User Story 3 - Credentials never leak in plaintext (Priority: P2)

An operator inspects application logs, an error report, or a startup failure message while diagnosing an issue. No credential value (API key, database password, service token, etc.) appears anywhere in that output in plaintext.

**Why this priority**: Protects against accidental credential disclosure through routine operational activity (log review, error reporting, bug reports that include console output) — a real risk once every configuration group is surfaced consistently in startup/validation messages per User Story 1.

**Independent Test**: Trigger a configuration validation failure and a normal startup with logging enabled; inspect all resulting output and confirm no credential value appears in plaintext in either case.

**Acceptance Scenarios**:

1. **Given** a credential-shaped configuration value is set, **When** the application logs its configuration state or a validation error mentions that value's name, **Then** the value itself does not appear in the output.
2. **Given** a developer or tool prints the in-memory configuration object for debugging, **When** that output is produced, **Then** credential values are masked rather than shown in plaintext.

---

### User Story 4 - Complete, trustworthy environment template (Priority: P3)

A developer sets up the project for the first time by copying the example environment file. Every value the service actually requires to run is present in that template, so following it produces a working setup without needing to discover missing variables by trial and error.

**Why this priority**: Lower priority than the reliability/security stories above, but directly affects first-run experience and is cheap to get right once the required-configuration list is finalized by the other stories.

**Independent Test**: Copy the example environment file as-is (substituting only placeholder secrets with real ones), start the service, and confirm no required variable is missing.

**Acceptance Scenarios**:

1. **Given** the example environment template, **When** every variable in it is given a real value and the service is started, **Then** no required configuration is reported missing.
2. **Given** the set of variables the service actually requires, **When** compared against the example template, **Then** every required variable is present in the template.

---

### Edge Cases

- What happens when the environment file is missing entirely (not just incomplete)?
- What happens when a test run needs to exercise the service without a live backend database available? Backend database access is required in every real deployment (resolved below), so such runs must supply placeholder credentials rather than relying on an unconfigured/optional state, consistent with how storage and document-processing credentials are already handled in tests today.
- What happens when a deterministic test/smoke-test run needs a configuration value that differs from both the environment file and the service's normal default, specifically to guarantee isolation from the developer's real environment?
- What happens when a new required configuration group is added in the future — is there a consistent, expected place to declare "this is required" and "this is how it fails fast"?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The service's own configuration MUST be defined in exactly one authoritative place; no other layer involved in starting the service (e.g. the container-orchestration configuration) may declare a conflicting default for the same setting that could silently override it.
- **FR-002**: Every required configuration group MUST be validated at startup, failing immediately with a message that identifies exactly which value(s) are missing or left at a placeholder — this MUST include the service's own database credentials, which currently has no such validation.
- **FR-003**: Configuration validation logic MUST be testable in isolation (i.e., a test can exercise "this configuration is invalid" and assert the resulting failure) without depending on or mutating shared process-wide state.
- **FR-004**: Related configuration settings MUST be organized into clearly named groups by domain (e.g. language-model settings, embedding settings, the service's own database, the backend's read-only database, object storage, document processing, observability, logging), so a developer can locate and reason about all settings for a given concern together.
- **FR-005**: Backend database access MUST be treated as required in every real deployment: missing or placeholder backend database credentials MUST fail startup immediately, the same as the service's other required configuration groups — not silently disabled or deferred to first use. (This is a classification decision — backend database access joins the set of "required configuration groups" that FR-002's fail-fast mechanism already covers; FR-002 is what enforces it once so classified.)
- **FR-006**: Credential-shaped configuration values (API keys, database passwords, service tokens, and equivalents) MUST never be exposed in plaintext through logs, error messages, or any textual representation of the configuration produced during normal operation or startup failure.
- **FR-007**: The example environment template MUST list every variable required to run the service, and MUST be kept in sync whenever required configuration changes.
- **FR-008**: Overrides declared at the container-orchestration layer MUST be used only where a specific run (e.g. a deterministic, isolated smoke test) needs to force a value regardless of the environment file's contents — never as a parallel set of defaults for the service's normal operation.

### Key Entities

- **Configuration Group**: A named collection of related settings sharing one domain (LLM, embeddings, own database, backend database, storage, document processing, observability, logging). Each group has a required/optional status and, where required, a validation rule that fails startup on missing or placeholder values.
- **Environment File**: The single authoritative source of values for a given running instance of the service (local developer machine, CI, or deployment).
- **Deterministic Override**: A value forced at the container-orchestration layer for a specific, isolated run (e.g. a smoke test), intentionally bypassing the environment file.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer who clones the repository and populates only the example environment template can start the service successfully on the first attempt, with no undocumented required value discovered by trial and error.
- **SC-002**: 100% of required configuration groups produce an immediate, actionable startup failure when misconfigured (up from a subset today).
- **SC-003**: No configuration setting has more than one place where its default value is declared for normal (non-test-isolation) operation.
- **SC-004**: A review of application logs and error output under both normal operation and a triggered configuration failure finds zero credential values exposed in plaintext.
- **SC-005**: A line-by-line comparison of the example environment template against the service's actual required configuration finds zero gaps in either direction.

## Assumptions

- "Fault-tolerant" in this context means configuration problems are caught deterministically and early (at startup), not that the service tolerates running with invalid configuration.
- The set of required configuration groups existing today (LLM/embeddings, own database, object storage, document processing, observability, service-to-service auth) stays materially the same; this effort changes how they are organized and validated, not what they are. Backend database access joins this required set (previously legitimately optional, resolved during clarification) since every real deployment connects to it — test runs that don't need a live backend now supply placeholder credentials instead, matching the existing pattern for storage/document-processing credentials in the test suite.
- "Container-orchestration layer" refers to whatever mechanism assembles and starts the service's runtime environment in a given context (local development, CI smoke testing, deployment) — the requirements here describe its relationship to the environment file, not a specific tool.
- Existing deterministic test/smoke-test isolation behavior (forcing specific values regardless of the environment file, to guarantee a run has no dependency on a developer's local setup) is preserved, not removed, by this effort.
