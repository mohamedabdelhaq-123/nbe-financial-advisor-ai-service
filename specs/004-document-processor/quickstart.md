# Quickstart: Statement Document Processor

Validation guide for the `POST /internal/ingestion/process` endpoint once implemented. See
[contracts/ingestion-process.md](contracts/ingestion-process.md) for the full request/response
shape and [data-model.md](data-model.md) for what gets read/written.

## Prerequisites

- A reachable MinerU instance with `MINERU_API_URL`/`MINERU_API_KEY` set (`X-Api-Key` header) for
  the real-engine path below. `MockMineruClient` is explicitly deferred (research.md §8) — until it
  exists, `USE_MOCK_MINERU=1` has no effect on `get_mineru_client()`'s behavior, so unit tests use
  inline test doubles instead (see below), not this flag.
- `STORAGE_S3_*` settings pointed at a reachable S3-compatible store (SeaweedFS), plus
  `STORAGE_S3_OCR_BUCKET` set to an already-provisioned bucket (defaults to `pfm-statements-ocr`;
  per `specs/003-object-storage`, this service never creates the bucket itself).
- A `statement_files` row to test against, reachable via the read-only backend DB, whose
  `seaweed_file_id` points at a real, readable object (e.g. `pfm-statements-raw/<user_id>/<id>/original.pdf`).

## Unit-test validation (test doubles, no live services)

1. Start the service with `USE_MOCK_LLM=1`.
2. Unit tests exercise this path directly (no HTTP call needed, no `USE_MOCK_MINERU` involved):
   ```
   pytest tests/features/ingestion/ -v
   ```
3. Expected: tests inject a local test double implementing the `MineruClient` protocol (via
   monkeypatching `get_mineru_client`) rather than calling `HttpMineruClient`; `service.py`'s
   `process_statement()` still exercises the full storage-write + audit-write path against the
   Testcontainers-backed own DB and a mocked storage client.

## End-to-end validation (real MinerU + real object store)

1. Ensure a `statement_files` row exists with a valid `seaweed_file_id` pointing at a real object.
2. Call the endpoint:
   ```bash
   curl -X POST http://localhost:8001/internal/ingestion/process \
     -H "Authorization: Bearer $AI_SERVICE_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"statement_id": "<real-statement-uuid>"}'
   ```
3. **Expected response** (200):
   ```json
   {"prefix": "pfm-statements-ocr/<statement-uuid>/", "ocr_engine": "MinerU"}
   ```
4. **Verify persisted artifacts** — using the same S3-compatible client/credentials, confirm three
   objects exist under the returned prefix:
   - `<prefix>markdown.md` — non-empty text
   - `<prefix>content_list.json` — valid JSON array
   - `<prefix>images/...` — zero or more image files, matching what MinerU extracted
5. **Verify the audit row** — query the own DB's `ai_audit_log` table for the most recent row with
   `action = 'ingestion.process'` and confirm `detail_json` contains the same `statement_id` and
   `prefix` from step 3.

## Failure-path checks (spec edge cases)

- Unknown `statement_id` (a well-formed UUID not present in `statement_files`) → expect `404`,
  and confirm no objects were written and no audit row was created.
- A `statement_files` row whose `seaweed_file_id` points at a missing/unreadable object → expect
  `502` with a message identifying the source-retrieval failure.
- MinerU unreachable (stop the `mineru-api` container, or point `MINERU_API_URL` at an unreachable
  address) → expect `502` with a message identifying the processing-engine failure.

## Out of scope for this quickstart

- Normalization/column-mapping of the extracted content into transactions — not part of this
  feature.
- Any check of the source document upload path (`statement_files` creation) — that's the
  backend's own responsibility, assumed to already exist for this validation.
