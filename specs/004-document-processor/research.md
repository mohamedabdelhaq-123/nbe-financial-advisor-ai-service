# Phase 0 Research: Statement Document Processor

## 1. MinerU response mode

**Decision**: Call `POST /file_parse` with `response_format_zip=true`, `return_md=true`,
`return_content_list=true`, `return_images=true`.

**Rationale**: The confirmed JSON-mode example response (`content_list` returned as a
JSON-*encoded string* nested inside a per-filename `results` object) is awkward to persist as
separate artifact files. ZIP mode gives back the three artifact kinds (markdown, `content_list.json`,
images) as discrete files, which map directly onto "three objects under one key prefix" — the
shape this feature needs to persist to object storage.

**Alternatives considered**: JSON mode (rejected — would require re-serializing `content_list`
back to a `.json` file ourselves instead of getting one from MinerU directly, and images would
arrive as base64 strings needing manual decoding before writing to storage — strictly more work
for the same outcome).

**Confirmed against a real MinerU instance** (`MINERU_API_URL`/`MINERU_API_KEY` from `.env`,
`backend=hybrid-engine` default, `parse_method=auto` default): the assumed ZIP layout was wrong in
two ways, both now fixed in `_extract_artifacts_from_zip()`:

1. **Files are nested** under `{stem}/{backend_mode}/` (e.g. `mineru_test/hybrid_auto/mineru_test.md`),
   not at the ZIP root. Extraction already matched by basename rather than full path, so this
   required no code change — just confirms the "don't assume fixed paths" approach was correct.
2. **The content-list file is not literally named `content_list.json`** — it's
   `{stem}_content_list.json` (e.g. `mineru_test_content_list.json`), and MinerU *also* emits a
   second variant, `{stem}_content_list_v2.json`, with a different, more deeply nested schema
   (arrays of arrays, no `page_idx`/`bbox` at the top level). The original exact-match on
   `content_list.json` missed the real file entirely (it fell through into the images bucket,
   silently misclassified) and had no exclusion for the `_v2` variant. Fixed: match
   `base.endswith("_content_list.json")` (in addition to the exact-match, kept as a fallback), and
   explicitly skip anything ending `_content_list_v2.json` before that check. The plain (non-v2)
   file was chosen because its shape — flat list of `{type, text/table_body, bbox, page_idx}`
   objects — matches the JSON-mode example response confirmed earlier in this project, whereas v2's
   shape does not match anything this feature's contract documents.

The markdown filename (`{stem}.md`) matched the original by-extension assumption correctly; no
images were present in the single-page text test document used, so image nesting (e.g. an
`images/` subdirectory versus flat) remains unconfirmed — the existing "extract by basename,
tolerate any depth" approach should handle either case, but this is worth a second look the first
time a real image-bearing statement is processed.

## 2. Language hint (`lang_list`)

**Decision**: `lang_list=["arabic"]`.

**Rationale**: NBE bank statements are Egyptian/Arabic-context financial documents; MinerU's
`arabic` option is described as covering "Arabic, Persian, Uyghur, Urdu, Pashto, Kurdish, Sindhi,
Balochi, English" — the right superset for this domain. The API default (`["ch"]`, Chinese-first)
would silently degrade OCR accuracy on these documents.

**Alternatives considered**: Leaving the default (`ch`) — rejected, wrong language family for the
document domain.

## 3. MinerU authentication and settings names

**Decision**: Config settings are named `mineru_api_url: str = ""` and `mineru_api_key: str = ""`
— matching the names already present in `.env.example` (`MINERU_API_URL`, `MINERU_API_KEY`), no
renaming/reconciliation needed. Send the key as `X-Api-Key: {settings.mineru_api_key}` (not an
`Authorization: Bearer` header) when `mineru_api_key` is non-empty; omit the header entirely when
it's empty. `mineru_api_url` is the only fail-fast-required MinerU setting when not in mock mode;
`mineru_api_key` stays optional.

**Rationale**: Confirmed directly by the requester: the deployed MinerU instance expects its
credential via an `X-Api-Key` header, not Bearer auth — this supersedes the earlier (unconfirmed)
Bearer-auth assumption. Keeping `mineru_api_key` optional still accommodates a self-hosted instance
with no fronting auth at all.

**Alternatives considered**: `Authorization: Bearer` header (the earlier draft's assumption) —
superseded by direct confirmation from the requester. `mineru_base_url`/`mineru_api_token` as
setting names — superseded in favor of matching the existing `.env.example` names exactly
(`mineru_api_url`/`mineru_api_key`), avoiding an unnecessary rename.

## 4. Object storage bucket for OCR output

**Decision**: Add a dedicated setting, `storage_s3_ocr_bucket: str = "pfm-statements-ocr"`, and
read it from `settings` at every write site in `ingestion/service.py` — never hardcode the bucket
name as a string literal in code. The default matches this deployment's current value (also seen
in `tests/conftest.py`'s `STORAGE_S3_BUCKET` default), but the name is looked up through config so
it can be changed per environment without a code change, and so this feature's output bucket stays
explicit and independent of whatever `settings.storage_s3_bucket` ends up meaning for other
features later (e.g. chat attachments, per the generic example in `specs/003-object-storage`).

**Rationale**: Reusing the generic `settings.storage_s3_bucket` setting would silently couple this
feature's output location to whatever any other feature configures that shared setting to mean;
today they happen to coincide only because nothing else has claimed `storage_s3_bucket` yet. A
named, feature-specific setting keeps that coincidence from becoming an implicit dependency.

**Alternatives considered**: Reusing `settings.storage_s3_bucket` — rejected per explicit
instruction: the OCR bucket must be its own configured value, not hardcoded or borrowed from an
unrelated shared setting.

## 5. Reading the *source* statement from a different bucket

**Decision**: `StatementFiles.seaweed_file_id` is a `"{bucket}/{path}"` string (e.g.
`pfm-statements-raw/{user_id}/{statement_id}/original.{ext}`). Split it on the first `/` into
`(source_bucket, source_key)` and call `get_object(Bucket=source_bucket, Key=source_key)` — an
explicit `Bucket` argument, independent of `settings.storage_s3_bucket`.

**Rationale**: `get_storage_backend()` returns a plain, unscoped aioboto3 S3 client (confirmed by
reading `app/core/storage.py`) — nothing in its contract locks a caller to
`settings.storage_s3_bucket`; that name is only a *convention* other call sites happen to follow.
Reading from a different, Django-owned bucket (`pfm-statements-raw`) for input while writing to
this service's own bucket (`pfm-statements-ocr`) for output requires no change to the storage
module itself.

**Alternatives considered**: Extending `get_storage_backend()`/`validate_storage_key()` to accept a
bucket override parameter — rejected as unnecessary; the existing client already supports this via
the standard boto3 `Bucket=` keyword on each call.

## 6. Cross-slice audit write

**Decision**: Call the existing `app.core.audit.record_audit(session, *, user_id, action, detail)`
helper from `ingestion/service.py`, rather than constructing `AiAuditLog` directly or adding a new
audit-writing function.

**Rationale**: This helper already exists and is already used by `chat/service.py` — it wasn't
visible during initial exploration because `app/features/audit/` only exposed a model at the time,
with no obvious service function; the actual established convention lives at `app/core/audit.py`,
one level up from the feature slice, not inside `app/features/audit/`. An earlier draft of this
plan added a duplicate `app/features/audit/service.py` before this was discovered during
implementation; that duplicate was removed in favor of the existing helper. One correction was
needed at the call site: `record_audit()` only does `session.add(row)` + `await session.flush()`,
it never commits — `ingestion/service.py` calls `await session.commit()` itself right after, since
this call site needs the row durably persisted (unlike `chat/service.py`'s best-effort, wrapped in
a bare `try/except: pass`, which — as a side effect of the same missing commit — never actually
persists its `"chat_turn"` audit rows either; that's a pre-existing gap in `chat/service.py`, out of
scope to fix here).

**Alternatives considered**: A new `app/features/audit/service.py::record()` function (the
initial draft's approach) — superseded once `app.core.audit.record_audit()` was found; keeping both
would just be a duplicate, inconsistent writer for the same table. Constructing `AiAuditLog(...)`
inline in `ingestion/service.py` — rejected as a Principle V violation (reaching into another
slice's model directly).

## 7. HTTP client lifecycle for the MinerU call

**Decision**: Open a fresh `httpx.AsyncClient` as an async context manager per call, with an
explicit generous timeout (e.g. connect 10s, read 120s — MinerU parses can be slow, especially cold
GPU starts), rather than a held singleton client.

**Rationale**: Mirrors the documented rationale in `app/core/storage.py` for
`get_storage_backend()` ("a new client is opened per call... cheap, and avoids any
event-loop-lifecycle coupling"). This capability's own call volume (one statement at a time,
triggered by backend ingestion, not a hot path) does not need connection-pool reuse across
requests badly enough to justify the added lifecycle complexity (e.g. `app.state`/`lifespan`
wiring) `get_chat_model()`'s `lru_cache` pattern would otherwise imply for a network client.

**Alternatives considered**: An `lru_cache`-memoized singleton (`get_chat_model()`'s pattern) —
workable for a lightweight SDK object like `ChatOpenAI`, but a held `httpx.AsyncClient` benefits
from explicit async lifecycle management (entering/closing) that a plain `lru_cache` function
doesn't provide, and there's no existing `lifespan`-managed slot for it without adding one — not
justified for this call pattern.

## 8. Mock-mode strategy — swappable client, not an in-function branch

**Decision**: Define a `MineruClient` interface (a `Protocol` with one method,
`async def parse_document(self, file_bytes: bytes, filename: str) -> ParsedDocument`), with a real
implementation (`HttpMineruClient`, the `X-Api-Key`/ZIP-mode HTTP call) behind a factory function,
`get_mineru_client() -> MineruClient`. `ingestion/service.py` calls `get_mineru_client()` and only
ever programs against the `MineruClient` interface — it never branches on `settings.use_mock_mineru`
itself, and cannot tell which concrete implementation it received. `get_mineru_client()` is the
*only* place that reads `settings.use_mock_mineru` to decide which implementation to construct.

**Explicitly deferred**: The mock implementation (`MockMineruClient`, returning fixed deterministic
artifacts in the exact same `ParsedDocument` shape the real client returns) is **not** built as
part of this feature — confirmed directly by the requester, who is pointing `MINERU_API_URL`/
`MINERU_API_KEY` at a real, reachable MinerU instance for now and will validate against it directly.
`get_mineru_client()` should still be written to select on `settings.use_mock_mineru` (so the
seam exists), but until `MockMineruClient` exists, unit tests that need a test double construct one
inline (a small local class or fixture implementing the `MineruClient` protocol) rather than relying
on mock-mode runtime behavior — this keeps Constitution I's mock-first requirement satisfied for
tests without blocking on the deferred mock implementation.

**Rationale**: The requester was explicit that consumers of the client (`service.py`, tests) must
not be able to tell mock from real — that rules out an `if settings.use_mock_mineru: ...` branch
inside `parse_document()` itself (the earlier draft's approach), since that couples the concrete
function to both code paths rather than letting the factory own the choice. A `Protocol` +
factory keeps `service.py` and its tests depending only on shape, matching how `get_chat_model()`
already keeps the LLM provider swappable behind one call site.

**Alternatives considered**: The originally-planned in-function short-circuit
(`if settings.use_mock_mineru: return canned_result`) — rejected per explicit instruction, since it
means the "same function" secretly has two behaviors rather than two interchangeable
implementations of one interface. Building `MockMineruClient` now anyway — rejected per explicit
instruction to defer it; real-server validation is happening first.
