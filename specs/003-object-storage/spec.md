# Feature Specification: Object Storage Infrastructure

**Feature Branch**: `003-object-storage`

**Created**: 2026-07-12

**Status**: Draft

**Input**: User description: "setup fs storage for our fastAPI application; we would need one to support s3 compatible object storage"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Persist and retrieve a blob from any feature (Priority: P1)

As a developer building a feature on this service (chat attachments,
generated analytics reports, uploaded statements, etc.), I need a single,
reliable way to store a binary blob and read it back later, so that I don't
have to write object-storage-protocol code inside every feature that needs
to persist a file.

**Why this priority**: Without this, no feature can durably persist a file at
all — every other capability that depends on file storage is blocked until
this exists. This is the minimum viable slice.

**Independent Test**: From application code (a service function, a
background job, or an agent/graph node), write a blob under a logical key
and read the same blob back byte-for-byte, using a running instance pointed
at a real configured object store.

**Acceptance Scenarios**:

1. **Given** the service is configured with a reachable object store and an
   existing bucket, **When** application code writes a blob under a logical
   key, **Then** a subsequent read of that same key returns the identical
   bytes.
2. **Given** a blob has been stored under a logical key, **When** application
   code checks whether that key exists, **Then** the check reports the blob
   is present.
3. **Given** a blob has been stored under a logical key, **When** application
   code deletes that key and then checks existence again, **Then** the check
   reports the blob is no longer present.
4. **Given** several blobs have been stored under keys sharing a common
   prefix, **When** application code lists blobs under that prefix, **Then**
   it receives exactly the logical keys of those blobs and no others.

---

### User Story 2 - Point the service at the operating environment's object store via configuration (Priority: P2)

As an operator deploying this service into a given environment, I need to
configure which object storage endpoint, bucket, and credentials the service
uses purely through environment configuration, so the same code runs
unchanged across local, staging, and production environments, each pointed
at its own object store instance.

**Why this priority**: The service must work against the operator's actual
S3-compatible object store (not a fixed provider), and different
environments will point at different instances/credentials. Without
config-driven targeting, every environment change requires a code change.

**Independent Test**: Set the object-store endpoint, bucket, region, and
credentials via configuration/environment variables, start the service, and
confirm application code can successfully store and retrieve a blob against
that specific instance — with no source-code changes between environments.

**Acceptance Scenarios**:

1. **Given** valid endpoint/bucket/credential configuration for a reachable
   S3-compatible object store, **When** the service starts, **Then** it
   starts successfully and storage operations against that store succeed.
2. **Given** the same code deployed in a different environment with
   different endpoint/bucket/credential configuration, **When** the service
   starts, **Then** it transparently talks to the newly configured store
   with no code changes.

---

### User Story 3 - Fail fast on incomplete storage configuration (Priority: P3)

As an operator, I need the service to refuse to start if required storage
configuration is missing or incomplete, so that a misconfiguration is caught
immediately at deployment time rather than surfacing later as a failed
request in production.

**Why this priority**: Silent misconfiguration that only fails at first use
is harder to diagnose and can slip past deployment checks. This is lower
priority than the core read/write capability but still an operational
safety requirement.

**Independent Test**: Start the service with incomplete storage credentials
(e.g. bucket set but access key missing) and confirm it fails to start
immediately, with an error message that identifies which configuration is
missing.

**Acceptance Scenarios**:

1. **Given** required storage configuration (bucket, access key, secret key)
   is incomplete, **When** the service starts, **Then** startup fails
   immediately with an explicit error naming the missing configuration.
2. **Given** required storage configuration is complete, **When** the
   service starts, **Then** startup succeeds without attempting any live
   connection to the object store at startup.

---

### Edge Cases

- What happens when application code supplies a logical key that attempts to
  escape the configured bucket namespace (e.g. contains `..` or is an
  absolute path)? The operation MUST be rejected before any network call is
  made, rather than silently writing outside the intended scope.
- What happens when the configured bucket does not exist on the target
  object store? Operations against it MUST fail explicitly (not silently
  succeed or auto-create the bucket).
- What happens when the configured object-store endpoint is unreachable?
  The operation MUST fail explicitly rather than hang indefinitely.
- What happens when application code tries to read or delete a key that was
  never stored? The operation MUST report the object doesn't exist rather
  than raising an ambiguous error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a way for internal application code to
  write a binary blob to object storage, addressed by a logical key.
- **FR-002**: System MUST provide a way for internal application code to
  read back a previously stored blob by its logical key, returning the
  exact bytes that were written.
- **FR-003**: System MUST provide a way to check whether a blob exists at a
  given logical key.
- **FR-004**: System MUST provide a way to delete a stored blob by its
  logical key.
- **FR-005**: System MUST provide a way to list the logical keys of blobs
  stored under a given key prefix.
- **FR-006**: System MUST target an S3-compatible object storage endpoint,
  with the endpoint, bucket, region, credentials, and addressing style all
  configurable without requiring a code change to switch environments or
  target stores.
- **FR-007**: System MUST reject, before making any network call, any
  logical key that could escape the configured bucket's namespace (e.g. via
  path traversal or an absolute path).
- **FR-008**: System MUST validate that required storage configuration
  (bucket, access key, secret key) is present at service startup and fail
  immediately with an explicit error if it is not, rather than deferring
  the failure to first use.
- **FR-009**: System MUST NOT create or provision the storage bucket
  itself — the bucket is expected to already exist on the target object
  store, pre-provisioned by whoever operates it.
- **FR-010**: This capability MUST be usable from any part of the internal
  codebase — request-handling code, background jobs, and agent/graph nodes
  alike — without requiring an active HTTP request context to use it.
- **FR-011**: System MUST NOT expose any HTTP endpoint for uploading or
  downloading blobs directly; this capability is internal-only and consumed
  by other parts of the codebase in-process.

### Key Entities

- **Stored Object**: A binary payload addressed by a logical key (a
  path-like string, e.g. `"chat/attachments/<id>.pdf"`), stored in exactly
  one configured bucket on the target S3-compatible object store. Has no
  attributes beyond its key and byte content from this capability's point
  of view — any metadata (owner, content type, retention) is the
  responsibility of the feature that stores it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can persist and retrieve a blob through this
  capability without writing any object-storage-protocol-specific code
  themselves.
- **SC-002**: The service can be pointed at a different S3-compatible
  object store instance (e.g. switching environments) purely through
  configuration changes, with zero source-code changes.
- **SC-003**: 100% of startup attempts with incomplete storage credentials
  fail at service startup rather than at first storage use.
- **SC-004**: 100% of storage operations using a key that would escape the
  configured bucket's namespace are rejected before any network call is
  made.

## Assumptions

- The target S3-compatible object store (SeaweedFS, in this service's
  deployment) is already deployed and reachable as shared infrastructure;
  this feature does not provision, run, or manage that infrastructure.
- The storage bucket already exists and is pre-provisioned by whoever
  operates the object store; this service never creates buckets itself.
- Blobs handled by this capability are moderate in size (e.g. chat
  attachments, small generated documents/reports) — large-file streaming
  optimization is out of scope for this initial version.
- No public HTTP endpoints are exposed for upload/download; this is
  internal infrastructure consumed in-process by other parts of the
  codebase, not a user-facing feature.
- Presigned URL generation for direct-to-client downloads is out of scope
  for this initial version; it may be added later if a feature needs it.
