# Feature Specification: Async Ingestion Endpoints

**Feature Branch**: `017-async-ingestion-endpoints`

**Created**: 2026-07-28

**Status**: Draft

**Input**: User description: "We should provide asynchronous endpoints, for the ingestion pipeline."

## Clarifications

### Session 2026-07-28

- Q: FR-009 (resolve jobs left non-terminal by a restart) and FR-012 (bound concurrent execution)
  both depend on whether more than one instance of the service may run at once, which the spec did
  not state. Must the async path be correct under multiple instances? → A: No — a single running
  instance is an explicit operational constraint of this feature. Jobs execute inside the running
  service process, and running multiple replicas is unsupported for the async path until a later
  feature adds exclusive job claiming.
- Q: FR-006 requires a succeeded job to carry its complete result, and FR-016 keeps job records 30
  days — where does that content live, given a normalization result contains full transaction detail
  and the real unmasked account number? → A: Stored inline in the job record for both steps. This is
  a second durable copy of full financial data in the service's own DB and MUST be treated as such:
  it is subject to the same protection as any other stored copy, and the plan's Constitution Check
  MUST justify it against Principle III's minimization and retention requirements rather than
  treating an internal DB as exempt.
- Q: SC-003 and SC-007 described caller-side outcomes (shorter timeouts, no jobs lost to gateway
  timeouts), but migrating the backend onto the async path is out of scope and the backend is a
  separate repository — is that migration part of this feature? → A: No — this feature is the AI
  service only. Both criteria are restated as service-side properties provable by this repository's
  own test suite; the real-caller outcome becomes the acceptance criterion of the follow-up backend
  change.
- Q: FR-012 required bounding concurrent execution without naming a limit or saying whether it is
  tunable — what limit, and configurable by whom? → A: A fixed constant of 2 concurrent jobs, with
  no configuration knob; the value changes only by code change. Note this service imposes no limit
  today, and the apparent ceiling comes from the caller's worker pool in a separate repository —
  that ceiling disappears once submission returns immediately, so this constant replaces it rather
  than mirroring it. **Superseded during planning (see below).**

### Post-clarification decisions (2026-07-28)

- **Concurrency bound dropped; execution on `BackgroundTasks`** (superseded again, below). The
  requester decided during `/speckit-plan` to use the framework's own background-task mechanism with
  no limit on concurrent executions, superseding the "fixed constant of 2" answer above.
- **Execution and persistence move to a job-queue library: SAQ on Postgres, worker in-process.** The
  requester asked for an idiomatic library rather than hand-rolled job persistence and chose arq;
  arq was then found to be in maintenance-only mode since Oct 2025, so SAQ — arq-inspired, actively
  maintained, and able to run on Postgres with no Redis — was selected instead. Consequences carried
  into the plan:
  - **FR-012 restated a second time**: concurrency is the worker's `concurrency` setting (a library
    knob, not hand-rolled machinery), so a bound exists again and excess submissions queue.
  - **FR-009 and SC-005 amended** (applied): SAQ *resumes* queued jobs after a restart rather than
    failing them, which is better for the caller but contrary to the original wording, which failed
    every non-terminal job. FR-009 now distinguishes the two cases — queued resumes, executing is
    swept to failed and not re-executed — and SC-005 is bounded by the sweep interval rather than a
    fixed minute, since the timing is now the runner's to determine. The spec's "best-effort
    execution, durable records" assumption below is correspondingly narrower: it applies to jobs
    interrupted mid-execution, not to queued work.
  - **Retention (FR-016) becomes the queue's `ttl`**, set to 30 days. There is no separate purge
    process, so that one setting carries the whole requirement.

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Submit extraction work and get an immediate acknowledgment (Priority: P1)

The backend asks this service to extract a previously uploaded statement and receives an immediate
acknowledgment carrying a job reference, instead of holding an open request for however long the
extraction takes. The extraction proceeds in the background; the backend is free to release the
worker that submitted it.

**Why this priority**: Extraction is the longest-running step in the pipeline (large multi-page
PDFs), and it is the step where a held-open request is most likely to be cut by an intermediate
timeout. Making this one step submittable is by itself a complete, deployable improvement — the
backend can move its extraction phase off a blocking call without any other part of this feature
existing.

**Independent Test**: Can be fully tested by submitting an extraction request for a known statement,
confirming the response arrives promptly with a job reference while work is still ongoing, and later
confirming the extracted artifacts were produced exactly as the existing blocking path produces
them.

**Acceptance Scenarios**:

1. **Given** a valid, previously uploaded statement, **When** the caller submits an extraction job,
   **Then** the caller receives an acknowledgment containing a unique job reference well before the
   extraction itself finishes.
2. **Given** an extraction job accepted for a statement, **When** the background work completes
   successfully, **Then** the same result content the blocking path returns is available against
   that job reference.
3. **Given** a submitted statement identifier that does not exist, **When** the caller submits an
   extraction job, **Then** the submission is rejected immediately with a not-found error and no job
   is created.

---

### User Story 2 - Check a job's progress and collect its result (Priority: P1)

The backend checks on a previously submitted job at its own pace and learns whether it is still
waiting, still running, finished successfully (with the full result), or failed (with a
human-readable reason it can store and show the user).

**Why this priority**: Without a way to read the outcome, a submitted job delivers nothing back to
the caller — this is the other half of the minimum viable async surface and must ship with User
Story 1.

**Independent Test**: Can be fully tested by submitting a job, reading its state while it runs,
reading it again after completion to collect the result, and reading a deliberately failed job to
confirm the failure reason is present and actionable.

**Acceptance Scenarios**:

1. **Given** a job that has been accepted but has not started, **When** the caller checks its state,
   **Then** the state reports as queued, with no result and no failure reason.
2. **Given** a job that is currently executing, **When** the caller checks its state, **Then** the
   state reports as running, with no result and no failure reason.
3. **Given** a job that has completed successfully, **When** the caller checks its state, **Then**
   the state reports as succeeded and the full result content is included.
4. **Given** a job that failed, **When** the caller checks its state, **Then** the state reports as
   failed and includes a human-readable reason describing what went wrong, in the same terms the
   blocking path reports errors today.
5. **Given** an unknown job reference, **When** the caller checks its state, **Then** the caller
   receives a not-found error.
6. **Given** a completed job, **When** the caller checks its state repeatedly, **Then** every check
   returns the same terminal state and result — reading a result does not consume or alter it.

---

### User Story 3 - Submit normalization work asynchronously (Priority: P2)

The backend asks this service to normalize a previously extracted statement's content and, as with
extraction, receives an immediate job reference rather than holding a request open for the duration
of the model work.

**Why this priority**: Normalization is the second-longest step and benefits from the same treatment,
but the extraction step is both slower and the more common timeout victim, so it delivers value
first. This story reuses the submission and status mechanics proven by Stories 1 and 2, so it is
additive rather than foundational.

**Independent Test**: Can be fully tested by submitting a normalization job against a known
extraction result, confirming the prompt acknowledgment, and later collecting a result identical in
content to what the blocking normalization path returns.

**Acceptance Scenarios**:

1. **Given** a valid, previously extracted statement result, **When** the caller submits a
   normalization job, **Then** the caller receives an acknowledgment containing a unique job
   reference well before normalization finishes.
2. **Given** a normalization job that completes successfully, **When** the caller collects its
   result, **Then** the result content matches what the blocking normalization path returns for the
   same input.
3. **Given** an extraction-result identifier that does not exist, **When** the caller submits a
   normalization job, **Then** the submission is rejected immediately with a not-found error and no
   job is created.

---

### User Story 4 - Repeat submissions do not duplicate work (Priority: P3)

When the same work is submitted twice — a double-clicked retry, a redelivered message, a caller that
did not record the first job reference — the service does not run the same expensive pipeline step
twice concurrently against the same target.

**Why this priority**: A correctness and cost safeguard rather than a capability. The pipeline is
usable without it (the backend already guards against overlapping phases on its side), but duplicate
model and OCR work is expensive and can produce conflicting stored artifacts.

**Independent Test**: Can be fully tested by submitting the same target twice in quick succession
and confirming the second submission is recognized as already in flight rather than starting a
second execution.

**Acceptance Scenarios**:

1. **Given** a job already queued or running for a target, **When** the same step is submitted again
   for that same target, **Then** the caller is pointed at the existing in-flight job rather than a
   second job being started.
2. **Given** a job that has already reached a terminal state for a target, **When** the same step is
   submitted again for that target, **Then** a new job is created and runs (a retry is allowed).

---

### Edge Cases

- **Service restarts while a job is in flight**: a job that had not started yet resumes and completes
  after the restart. A job that was mid-execution MUST NOT be left reporting as running forever; it
  moves to a terminal failed state with a reason indicating it was interrupted, so the caller can
  resubmit.
- **Caller never checks back**: an abandoned job still runs to completion and its record still ages
  out under the retention rule; it does not accumulate indefinitely.
- **Caller checks immediately after submitting**: the state is readable the instant the
  acknowledgment is returned — there is no window where a just-issued job reference reads as unknown.
- **Underlying step fails partway** (source document unreachable, extraction engine error, model
  failure): the job reaches the failed state carrying the same diagnostic detail the blocking path
  surfaces today, not a generic message.
- **Many jobs submitted at once**: every submission is accepted and begins executing; none is
  rejected or deferred. Sustained load is bounded by the caller's submission rate, not by this
  service.
- **Statement/extraction result deleted after submission but before execution**: the job reaches the
  failed state with a clear reason rather than hanging or crashing the worker.
- **Checking a job whose record has aged out**: reads as not-found, the same as an unknown reference.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The service MUST accept extraction work for a statement without holding the request
  open for the duration of the work, responding instead with an acknowledgment that carries a unique
  job reference.
- **FR-002**: The service MUST accept normalization work for an extraction result on the same terms
  as FR-001.
- **FR-003**: The service MUST validate the submitted target (statement or extraction result) at
  submission time and reject an unknown target immediately, creating no job record.
- **FR-004**: The service MUST expose a way for the caller to read a job's current state using only
  the job reference returned at submission.
- **FR-005**: A job's state MUST be exactly one of: queued, running, succeeded, or failed.
- **FR-006**: A job in the succeeded state MUST carry the complete result content for that pipeline
  step, identical in shape and values to what the existing blocking endpoint returns for the same
  input. The result content MUST be stored durably as part of the job record itself, so a status
  read is self-contained and does not depend on any other store remaining reachable.
- **FR-006a**: Because a stored normalization result is a second durable copy of full transaction
  detail and unmasked account numbers, job records MUST be readable only through the authenticated
  job-status surface (FR-013), MUST NOT be written to logs or telemetry exports in whole or in part,
  and MUST be removed on the retention clock in FR-016 with no archival copy retained.
- **FR-007**: A job in the failed state MUST carry a human-readable failure reason preserving the
  same diagnostic detail the existing blocking endpoint surfaces for the same failure.
- **FR-008**: Reading a job's state MUST be repeatable and non-destructive — the same read returns
  the same answer, and terminal states never change afterwards.
- **FR-009**: Job records MUST survive a service restart. A job that had not started executing MUST
  resume and run to completion after the restart. A job that was executing when the service stopped
  MUST be resolved to the failed state with a reason identifying it as interrupted, and MUST NOT be
  re-executed automatically. No job may remain readable as running indefinitely. (Revised — see
  Post-clarification decisions; the original wording failed every non-terminal job, which would
  discard queued work the runner can simply resume.)
- **FR-010**: The service MUST NOT start a second execution of the same pipeline step against a
  target that already has a queued or running job for that step; the repeat submission MUST resolve
  to the existing job's reference.
- **FR-011**: The service MUST allow a new job for a target whose previous job for that step has
  reached a terminal state, so a failed step can be retried.
- **FR-012**: The service MUST NOT reject a submission because other jobs are already running.
  Concurrent execution is bounded by the job runner's own concurrency setting, recorded as a
  documented constant; submissions beyond it wait in the queued state rather than being rejected.
  (Revised twice — see Post-clarification decisions.)
- **FR-013**: The asynchronous submission and status surfaces MUST require the same caller
  authentication as every other non-probe endpoint.
- **FR-014**: The existing blocking extraction and normalization endpoints MUST continue to work
  unchanged, so the caller can migrate one step at a time.
- **FR-015**: Every asynchronous execution MUST produce the same audit record its blocking
  counterpart produces, attributed to the same action, so switching to the asynchronous path leaves
  no gap in the audit trail.
- **FR-016**: Job records MUST be retained for a defined period after reaching a terminal state and
  MUST be removed once that period elapses, so job history does not accumulate without bound.
- **FR-017**: A job record MUST expose when it was submitted, when it started, and when it finished,
  so the caller and operators can reason about how long work waited and ran.
- **FR-018**: A failure inside one job MUST NOT prevent other queued or running jobs from executing
  or completing.
- **FR-019**: Jobs MUST execute within the running service itself, and the service MUST operate as a
  single instance for the asynchronous path. Running more than one instance is unsupported for this
  feature, because nothing prevents two instances from executing the same queued job or from one
  instance failing another's in-flight jobs during restart reconciliation (FR-009). This constraint
  MUST be stated wherever the service's deployment is documented.

### Key Entities

- **Ingestion Job**: One submitted unit of pipeline work. Identified by a unique reference given to
  the caller at submission. Records which pipeline step it performs (extraction or normalization),
  which target it acts on (a statement or an extraction result), its current state, submission /
  start / finish timestamps, and — once terminal — either the step's full result content or a
  human-readable failure reason. Owned entirely by this service; it references backend records by
  identifier only, never by an enforced relationship.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: Submitting either pipeline step returns an acknowledgment in under 2 seconds for 95%
  of submissions, regardless of how long the underlying work subsequently takes.
- **SC-002**: A statement whose end-to-end pipeline takes 10 minutes or more completes successfully
  through the asynchronous path, with no submission or status request ever exceeding the
  acknowledgment target in SC-001.
- **SC-003**: No asynchronous ingestion interaction holds a connection open longer than 60 seconds,
  so a caller can serve the entire pipeline with a 60-second request timeout — compared with the
  60-minute read timeout the blocking path requires today. Verified against the asynchronous
  endpoints directly; actually shortening the backend's timeout is follow-up work in that repository.
- **SC-004**: For every pipeline step and failure mode, the outcome reported through the
  asynchronous path (result content on success, diagnostic detail on failure) is equivalent to what
  the blocking path reports for the same input — verified across the full existing ingestion test
  suite.
- **SC-005**: After a service restart, 100% of jobs that had not started executing complete
  normally, and 100% of jobs that were executing report a terminal failed state within one sweep
  interval of the service becoming ready; none remain readable as running beyond that.
- **SC-006**: Submitting the same target twice within the same execution window results in exactly
  one execution of that pipeline step.
- **SC-008**: Multiple jobs submitted in quick succession all reach a terminal state, with none
  rejected and none left indefinitely non-terminal.
- **SC-007**: A submitted job runs to a terminal state and its result stays collectable even when
  the submitting caller disconnects immediately after acknowledgment — demonstrated on the existing
  large-statement validation benchmark (3+ pages, 40+ transactions), where the blocking path is the
  one exposed to caller-side and gateway timeouts.

## Assumptions

- **Polling, not callbacks**: the caller learns of completion by reading job state, not by this
  service calling back into the backend. This follows the standing boundary that this service is
  invoked by the backend and never initiates traffic toward it; a callback would invert that
  direction and require new inbound surface and credentials on the backend side.
- **Additive, and scoped to this service**: the asynchronous surfaces are added alongside today's
  blocking extraction and normalization endpoints, which stay behaviorally unchanged. Migrating the
  backend's pipeline tasks onto the asynchronous path, shortening its request timeout, and
  eventually retiring the blocking endpoints are all follow-up work in the backend repository — no
  change outside this service is part of this feature, and every success criterion here is provable
  by this repository's own test suite.
- **Two independent steps, not one combined job**: extraction and normalization remain separately
  submittable and are threaded by the caller exactly as they are today (a normalization job names
  the extraction result a prior extraction job produced). No single "run the whole pipeline" job is
  introduced.
- **Best-effort execution, durable records**: job records are durable, and work that has not started
  survives a restart and runs afterwards. Execution that was *already underway* is not resumed — an
  interrupted job is reported as failed and the caller retries, matching the caller's existing retry
  model, where a failed phase is re-driven by an explicit retry rather than automatically resumed.
- **Single instance** (FR-019): the service runs as one process, matching how it is deployed today.
  Exclusive job claiming, ownership heartbeats, and a separate worker process are all deliberately
  out of scope — they exist to make replicas safe, and there are no replicas. Scaling the async path
  horizontally is a later feature that must add claiming before a second instance is started.
- **Result content is unchanged**: the asynchronous path returns the same result payloads the
  blocking endpoints define today; this feature changes *when and how* a result is delivered, not
  *what* a result contains.
- **Retention**: terminal job records are kept for 30 days, matching an ordinary operational-history
  window, then removed. No caller requirement for longer history is known.
- **No caller-visible queue position or progress percentage**: state is coarse (queued / running /
  succeeded / failed). Fine-grained progress reporting is out of scope.
- **No cancellation**: a submitted job cannot be cancelled by the caller in this feature.
- **Job records are internal-only**: they carry pipeline results and identifiers already exchanged
  with the caller today, and are subject to the same minimization rules as any other stored or
  exported data. Storing results inline (FR-006) is a deliberate tradeoff chosen for self-contained
  status reads over avoiding a duplicate copy of financial data; FR-006a states the protections that
  come with it, and the plan must clear it at the Constitution Check gate rather than assume it.
