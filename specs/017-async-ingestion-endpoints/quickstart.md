# Quickstart: Async Ingestion Endpoints

Validation guide for the asynchronous ingestion job surface. Endpoint shapes are in
[contracts/ingestion-jobs.md](contracts/ingestion-jobs.md); the job record and its state machine are
in [data-model.md](data-model.md).

## Prerequisites

- The own DB migrated to head (`uv run alembic upgrade head`) for the `ai_ingestion_job_targets`
  mapping table. SAQ's own tables (`saq_jobs`, `saq_stats`, `saq_versions`) need no migration — it
  creates them itself when the queue connects at startup.
- Confirm the SAQ settings are the overridden ones, not the defaults — this is the single most
  likely cause of confusing behavior below:

  ```sql
  -- after one job completes: expire_at should be ~30 days out, not ~10 minutes
  SELECT key, status, to_timestamp(expire_at) FROM saq_jobs ORDER BY expire_at DESC LIMIT 5;
  ```

  **Note on querying `saq_jobs`**: only `key`, `status`, `queue`, `priority`, `group_key`,
  `scheduled`, and `expire_at` are real columns. Everything else — timestamps, result, error,
  attempts — is inside the `job` BYTEA blob, so it can't be `SELECT`ed or `UPDATE`d directly.
  Read those through the status endpoint below.

  A job that dies at exactly 10 seconds means `timeout` is still at its default.
- The same setup the blocking endpoints already need: read-only backend DB access, object storage
  reachable, MinerU reachable (or `AI_SERVICE_MINERU__USE_MOCK=1`), and LLM config (or
  `AI_SERVICE_CHAT_MODEL__USE_MOCK=1`).
- A real `statement_files` row for the extraction checks, and a `statement_ocr_results` row for the
  normalization checks — same targets the blocking endpoints take.
- `AI_SERVICE_TOKEN` exported for the `curl` calls below.
- **Exactly one instance running** (FR-019), with the worker in-process — no separate worker
  container to start.

## Offline test validation (no live services)

```bash
uv run pytest tests/features/ingestion/ -v
uv run pytest tests/integration/ -v          # needs Docker (Testcontainers)
```

Expected coverage:

- Submission returns `202` with a job reference; the status read immediately afterwards succeeds
  (no unknown-reference window).
- Submitting an unknown `statement_id` / `ocr_result_id` returns `404` and creates no row.
- Terminal `succeeded` payload equals the blocking endpoint's response for the same input, and a
  `failed` job's `error` equals the blocking endpoint's `detail` for the same failure.
- Repeated status reads return identical terminal content (FR-008).
- Every row of the SAQ-status → contract-state mapping, asserted as a pure function (no queue
  involved): `NEW`/`QUEUED` → `queued`, `ACTIVE` → `running`, `COMPLETE` + `ok` → `succeeded`,
  `COMPLETE` + `!ok` → `failed` with the pipeline's own message, `FAILED`/`ABORTED` → `failed` with a
  generic message and no stack trace in the response.
- Against real Postgres with real SAQ: a second submission for a target with a live job returns the
  same key; a submission after that job is terminal returns a **new** key; `ttl` is 30 days on a
  completed job, and the sweep deletes it once `expire_at` has passed.
- `alembic upgrade head` creates `ai_ingestion_job_targets`.

## Happy path (US1 + US2)

1. Submit extraction and note how fast the acknowledgment comes back:

   ```bash
   time curl -s -X POST http://localhost:8001/internal/ingestion/jobs/process \
     -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"statement_id": "<real-statement-uuid>"}'
   ```

   **Expected**: `202`, a `job_id`, `"state": "queued"`, returned in well under 2s (SC-001) even
   though extraction itself will run for minutes.

2. Read it back immediately, then poll:

   ```bash
   watch -n5 "curl -s http://localhost:8001/internal/ingestion/jobs/<job_id> \
     -H 'Authorization: Bearer $AI_SERVICE_TOKEN'"
   ```

   **Expected**: `queued` (possibly skipped if a slot was free), then `running` with `started_at`
   set, then `succeeded` with `finished_at` and `result`.

3. Compare the result against the blocking path: run `POST /internal/ingestion/process` for a
   comparable statement and diff the bodies. **Expected**: `result` is field-for-field what the
   blocking endpoint returns (SC-004).

4. Read the completed job several more times. **Expected**: identical response every time; nothing
   is consumed (FR-008).

5. Confirm the audit trail: one `ingestion.process` row in `ai_audit_log` for this execution, exactly
   as the blocking path writes (FR-015).

   ```sql
   SELECT action, detail_json, created_at FROM ai_audit_log ORDER BY created_at DESC LIMIT 5;
   ```

6. Repeat steps 1–5 with `POST /internal/ingestion/jobs/normalize` and a real `ocr_result_id` (US3).

## Timeout behavior (SC-003, SC-007)

1. Drive the full pipeline through the async routes with a **60-second** client timeout:

   ```bash
   curl --max-time 60 -X POST http://localhost:8001/internal/ingestion/jobs/process ...
   # then poll status with --max-time 60 until terminal
   ```

   **Expected**: no call ever approaches 60s — compare against the blocking path, which needs a
   60-minute read timeout for the same statement.

2. Disconnect immediately after acknowledgment (`--max-time 3`, or Ctrl-C the curl), then poll the
   job later from a fresh connection. Use the large-statement benchmark (3+ pages, 40+ transactions).
   **Expected**: the job still reaches `succeeded` and its result is still collectable (SC-007) —
   the submitting connection's fate does not affect execution.

## Many concurrent submissions (SC-008, FR-012)

1. Submit more jobs across distinct targets than the worker's `concurrency` setting allows.
2. Watch SAQ's own record:

   ```sql
   SELECT status, count(*) FROM saq_jobs GROUP BY status;
   ```

   **Expected**: no more than `WORKER_CONCURRENCY` rows in `active` at any sampled moment; the rest
   sit in `queued` — none rejected — and every one eventually reaches a terminal status.

## Duplicate submission (US4, SC-006)

1. Submit the same `statement_id` twice within a second.
2. **Expected**: both responses carry the **same** `job_id` and the same `submitted_at`; exactly one
   execution occurs — verify by counting `ingestion.process` audit rows for that statement (exactly
   one) and by confirming one `saq_jobs` row for that key.
3. After the job reaches a terminal state — and **while its record is still present**, which is the
   case that would break under naive key-based dedup — submit the same statement again.
   **Expected**: a **new** `job_id`, a second `saq_jobs` row, and the mapping row's `job_key` now
   pointing at the new job (FR-011):

   ```sql
   SELECT step, target_id, job_key FROM ai_ingestion_job_targets WHERE target_id = '<statement-uuid>';
   ```

4. **Expected**: the first job's status read still returns its original terminal content, unchanged
   by the retry (FR-008).

## Restart behavior (FR-009, SC-005 — both as amended)

Two distinct cases that behave differently; verify each separately.

**Case A — job was still `queued`:**

1. Submit several jobs so at least one is waiting; hard-kill the container (`docker kill`), restart.
2. **Expected**: the queued job **resumes** and completes normally. It is *not* failed (FR-009 as
   amended — the original wording would have discarded this work).

**Case B — job was executing:**

1. Submit a job for a slow statement; wait until it reads `running`; hard-kill and restart.
2. Poll it, and time how long the transition takes:

   **Expected**: it reaches `failed` with an interrupted reason once SAQ's sweep notices the missing
   heartbeat, and it is **not** retried (`retries=1`). Record the actual elapsed time — SC-005's
   one-minute bound now depends on the sweep interval and the job `heartbeat` value, so this
   measurement is what tells you whether those constants are set correctly.

3. Confirm nothing is stuck:

   ```sql
   SELECT key, status FROM saq_jobs WHERE status IN ('active', 'aborting');
   ```

## Failure fidelity and isolation (FR-007, FR-018)

1. Force a failure — point MinerU at an unreachable URL, or delete the target statement after
   submitting but before execution starts (submit several jobs first so the target one waits in
   `queued`).
2. **Expected**: that job reaches `failed` carrying the same diagnostic string the blocking endpoint
   returns for that condition (e.g. `document processing engine failed: …`, `statement not found`),
   not a generic message.
3. **Expected**: every other queued/running job still completes normally.

## Retention (FR-016, FR-006a)

Retention is entirely SAQ's `ttl` plus its sweep — there is no purge process of ours — so this check
is verifying one setting. **Do it first**, because at the default `ttl` of 600s the results would
vanish ten minutes after completion and every other check here would confuse you.

1. Confirm the window on a completed job:

   ```sql
   SELECT key, status, to_timestamp(expire_at) FROM saq_jobs WHERE key = '<job_id>';
   ```

   **Expected**: `expire_at` roughly 30 days out, not 10 minutes. (`completed` lives in the job
   blob, so compare against the `finished_at` the status endpoint reports.)

2. Full-window verification takes 30 days, so force it — back-date `expire_at` past now and wait for
   the next sweep:

   ```sql
   UPDATE saq_jobs SET expire_at = extract(epoch from now()) - 1 WHERE key = '<job_id>';
   ```

3. **Expected**: the row is deleted, and `GET /internal/ingestion/jobs/<job_id>` returns `404` — the
   same answer as an unknown reference. Confirm no copy of the result survives anywhere else in the
   own DB; the mapping row in `ai_ingestion_job_targets` may remain, and should contain no result
   content at all.

## Data-protection checks (FR-006a)

1. With a `succeeded` normalization job in hand, grep the service logs for content from its result —
   account number, merchant strings, amounts:

   ```bash
   docker compose -f compose/docker-compose.yml logs ai-service | grep -F '<account-number>'
   ```

   **Expected**: no hits. Job logging records references and states, never payloads.

2. If Langfuse is enabled, confirm no new trace or span carries the job result. The job machinery
   makes no model call of its own; the only traces are the ones normalization already produced.

3. Call the status route with no token and with a wrong token. **Expected**: `401` both times — the
   stored financial content is unreachable without the shared secret (FR-013).
