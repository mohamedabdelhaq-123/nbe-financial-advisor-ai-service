# Quickstart: Statement Transaction Normalization

Validation guide for the `POST /internal/ingestion/normalize` endpoint once implemented. See
[contracts/ingestion-normalize.md](contracts/ingestion-normalize.md) for the full request/response
shape and [data-model.md](data-model.md) for what gets read/written.

## Prerequisites

- A `statement_ocr_results` row to test against (Part 1's output), reachable via the read-only
  backend DB, whose `statement_id` has real `markdown.md`/`content_list.json` objects already
  written at `{STORAGE_S3_OCR_BUCKET}/{statement_id}/` (i.e. `/internal/ingestion/process` has
  already been run for it).
- The `categories` table migrated and seeded (`alembic upgrade head`) — this feature's migration
  creates and seeds it as part of the same own-DB Alembic chain everything else uses.
- `OPENAI_BASE_URL`/`OPENAI_API_KEY`/`MODEL_NAME` set for the real-LLM path below (same settings
  `plan`/`chat` already require); `USE_MOCK_LLM=1` for the offline path.

## Unit-test validation (mock LLM, no live services)

1. Start the service with `USE_MOCK_LLM=1`.
2. Run:
   ```
   pytest tests/features/ingestion/ -v
   ```
3. Expected: `normalizer.py`'s LLM call short-circuits per `settings.use_mock_llm` (same pattern as
   `plan/service.py`); `service.py`'s `normalize_statement()` still exercises the full
   storage-read/write + duplicate-match query + audit-write path against fakes/Testcontainers, and
   `test_categories.py` exercises `resolve_category()` and the migration/seed data against the real
   Testcontainers-backed own DB (`own_pg`/`own_db_url` fixtures).

## End-to-end validation (real LLM)

1. Ensure a `statement_ocr_results` row exists whose `statement_id` has Part 1 artifacts already in
   storage.
2. Call the endpoint:
   ```bash
   curl -X POST http://localhost:8001/internal/ingestion/normalize \
     -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"ocr_result_id": "<real-ocr-result-uuid>"}'
   ```
3. **Expected response** (200): a body matching
   [contracts/ingestion-normalize.md](contracts/ingestion-normalize.md)'s success shape —
   `normalized_json` with `bank_name`, `account_hint`, and a `transactions` array, plus
   `model_used`.
4. **Verify the persisted artifact** — using the same S3-compatible client/credentials, confirm
   `{bucket}/{statement_id}/normalized.json` exists and matches the response's `normalized_json`
   byte-for-byte.
5. **Verify every transaction's category** is one of the seeded `categories.name` values (query the
   own DB's `categories` table to confirm).
6. **Verify the audit row** — query the own DB's `ai_audit_log` table for the most recent row with
   `action = 'ingestion.normalize'` and confirm `detail_json` contains the same `statement_id` and
   `ocr_result_id`.

## Duplicate-flagging check

1. Seed (or use an existing) `transactions` row for the same user with a known amount and date.
2. Normalize a statement whose extracted content includes a transaction with that same amount and
   a date within 2 days of it.
3. **Expected**: that entry's `duplicate_of` is the existing row's `id`; other, non-matching
   entries have `duplicate_of: null`.

## Failure-path checks (spec edge cases)

- Unknown `ocr_result_id` (a well-formed UUID not present in `statement_ocr_results`) → expect
  `404`, and confirm no object was written and no audit row was created.
- The OCR artifacts referenced by the result are missing/unreadable in storage → expect `502`
  identifying the source-retrieval failure.
- LLM call fails or returns unparseable output → expect `502`, and confirm no object was written
  and no audit row was created.
- A statement whose content has no identifiable transactions → expect `200` with
  `transactions: []`, not an error.

## Out of scope for this quickstart

- Re-running document processing — this feature only reads Part 1's already-persisted artifacts.
- Persisting `statement_normalized` or any actual `transactions` ledger rows — that's the backend's
  responsibility using this endpoint's response.
- Adding/editing categories beyond the seeded starter set — a later capability.
