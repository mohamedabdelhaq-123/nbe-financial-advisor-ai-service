# Quickstart: Normalizer Pipeline Rework

Validation guide for the reworked `POST /internal/ingestion/normalize` pipeline. See
[contracts/ingestion-normalize.md](contracts/ingestion-normalize.md) for the full revised
request/response shape and [data-model.md](data-model.md) for what changed under the hood.

## Prerequisites

Same as spec 005's quickstart: a `statement_ocr_results` row with real `markdown.md`/
`content_list.json` already in storage (`/internal/ingestion/process` already run for it), the
`categories` table migrated/seeded, and `OPENAI_BASE_URL`/`OPENAI_API_KEY`/`MODEL_NAME` set for the
real-LLM path (`USE_MOCK_LLM=1` for the offline path). For the concurrency/observability checks below,
ideally use the same 3+ page / 40+ transaction real statement referenced throughout this feature's
research.md as the validation benchmark.

## Unit-test validation (mock LLM, no live services)

1. Start the service with `USE_MOCK_LLM=1`.
2. Run:
   ```
   pytest tests/features/ingestion/ -v
   ```
3. Expected: row-count-based chunking, the markdown renderer (one assertion per `content_list` entry
   type), the `extra_fields` list→dict conversion, `account_number`/`balance`/`merchant_normalized`
   passthrough, and the `Send`/reducer graph producing output identical to a forced-sequential run
   (`normalization_max_parallel_chunks=1`) all pass without any real model or Langfuse call.

## Output-shape validation (real LLM)

1. Call the endpoint exactly as before (request shape unchanged):
   ```bash
   curl -X POST http://localhost:8001/internal/ingestion/normalize \
     -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"ocr_result_id": "<real-ocr-result-uuid>"}'
   ```
2. **Verify `account_number`**: confirm the returned value matches the source statement's account
   number digit-for-digit, with no masking — cross-check against the source document directly, not
   against the old `account_hint` behavior.
3. **Verify `extra_fields` shape**: confirm both the statement-level and any transaction-level
   `extra_fields` are JSON **objects**, never arrays, in both the HTTP response and the persisted
   `{bucket}/{statement_id}/normalized.json` blob.
4. **Verify `balance`/`merchant_normalized`**: for a statement whose source states a running balance
   column, confirm at least one transaction carries a non-null `balance`; confirm
   `merchant_normalized` differs from `merchant_raw` where the source merchant text has an obvious
   canonical form (e.g. a POS reference string vs. a recognizable merchant name).
5. **Verify category/duplicate/audit behavior**: unchanged from spec 005's quickstart — re-run those
   same checks to confirm nothing regressed.

## Concurrency validation (SC-003)

1. Normalize the reference statement (3+ pages / 40+ transactions) with
   `AI_SERVICE_NORMALIZATION_MAX_PARALLEL_CHUNKS=1` and record wall-clock time.
2. Normalize the same statement again with the setting raised (e.g. `4`) and record wall-clock time.
3. **Expected**: the raised-concurrency run completes at least 2x faster (SC-003); the extracted
   transaction set is identical between both runs (FR-009) — diff the two `normalized.json` outputs
   transaction-by-transaction (ignoring `duplicate_of`, which may legitimately differ run-to-run if
   the first run's results were already persisted as ledger entries) to confirm.

## Chunking-quality validation (SC-004, FR-007)

1. Normalize the reference statement and confirm zero portions fail due to truncated/incomplete model
   output across at least 3 repeated runs.
2. Normalize (or construct a fixture from) a statement containing rows with unusually long
   transliterated merchant names and confirm portion boundaries still track transaction count, not
   character length — i.e. portions don't shrink to unusually few rows purely because of long text in
   a handful of rows.

## All-or-nothing failure validation (FR-016)

1. Using a fixture or a deliberately induced failure (e.g. a chunk crafted to trip the strict-mode
   validation retry path, or a mocked transient provider error exhausting `with_retry`'s 3 attempts on
   one chunk while others in the same run have already succeeded), confirm the **entire** normalization
   request fails — no partial `normalized.json` is written, no audit row is recorded, exactly as
   today's sequential failure behavior.

## Observability validation (FR-012, FR-015, User Story 6)

1. With the local Langfuse stack enabled (`make dev-up-observability` or equivalent per spec
   013's quickstart) and `LANGFUSE_ENABLED=true`, normalize the reference statement with concurrency
   raised above 1.
2. In the Langfuse UI, confirm: **(a)** every chunk's LLM call for this run appears grouped under one
   trace/call-tree for the statement — not as unrelated, ungrouped spans (this is the item
   research.md §8 flagged as needing empirical confirmation, not assumed from docs); **(b)** each
   span/call is individually filterable/identifiable by its `statement_id`/`ocr_result_id`/
   `chunk_index` metadata; **(c)** a `prompt_version` tag is present and stable across chunks within
   the same run.
3. Stop the Langfuse stack (or set `LANGFUSE_ENABLED=false`) and re-run normalization — confirm the
   request still succeeds and returns a complete result (FR-014/SC-008), matching this service's
   existing fail-open observability guarantee.
4. **Do not** treat this step as validating telemetry redaction for the new `account_number` field —
   that gap is explicitly out of scope for this feature (see plan.md Constitution Check); inspecting a
   trace here may show the real account number unredacted, which is the known, tracked exception, not
   a new bug to file against this feature.

## Out of scope for this quickstart

- Everything spec 005's quickstart already scoped out (re-running document processing, persisting
  ledger rows, category-management API).
- Coordinating or validating the backend-side consumption of the new response shape (FR-011) — that's
  a cross-repository dependency, not something this repo's quickstart can exercise.
- Extending telemetry redaction to cover account numbers — tracked separately, not validated here.
