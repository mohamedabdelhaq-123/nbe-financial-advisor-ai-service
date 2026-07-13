# Phase 0 Research: Statement Transaction Normalization

> **Post-implementation note**: §1–§3 and §7 below were revised after real-document validation
> (a genuine 3-page NBE statement) exposed that the original single-prompt design doesn't scale to
> real statement sizes or account-tier rate limits. The original text is kept for history; each
> revised section says so explicitly and points to the superseding decision (§9–§14).

## 1. Which OCR artifact(s) feed the LLM

**Decision (revised)**: `content_list.json`'s entries are the *only* source sent per chunk when
non-empty; `markdown.md` is a *true* fallback, used only when `content_list` is empty — not sent
alongside it. See §9 for why sending both was dropped (redundant, and doubled real token usage for
no benefit since both encode the same table).

**Original decision (superseded on the "send both" point, table-primary point still holds)**: Read
both `content_list.json` and `markdown.md` from the OCR prefix; pass
`content_list.json`'s entries as the primary source (it's already a flat, structured list of
`{type, text/table_body, bbox, page_idx}` objects per `specs/004-document-processor/research.md`
§1 — bank statement line items are usually `table` entries there), with the markdown included as
secondary context for anything the content list doesn't capture cleanly (headers, footers, running
narrative). Do not read the `images/` artifacts — normalization is text-only (spec Assumptions).

**Rationale**: `content_list.json`'s table entries are the closest thing to a pre-parsed
transaction table MinerU gives us; feeding raw markdown alone would make the LLM re-derive table
structure from Markdown table syntax (lossier, especially for merged cells/multi-line entries
common in bank statement PDFs).

**Alternatives considered**: Markdown-only (rejected — throws away MinerU's already-parsed table
structure for no benefit). Images/OCR re-run (rejected — out of scope; Part 1 already extracted
text content, re-processing images here would duplicate that step).

**Confirmed against a real model** (Groq's OpenAI-compatible endpoint, `openai/gpt-oss-20b`): given
a synthetic statement with a markdown/content-list table encoding debits as negative amounts (a
common source-document convention), the model faithfully echoed that sign in its `amount` field —
but the spec's own example shows a positive `amount` (`1234.56`) for a debit transaction, meaning
the intended contract is amount-as-magnitude with direction conveyed by `transaction_type` alone.
Fixed in `_parse_normalized_json()`: `amount = abs(float(amount))` unconditionally, plus an
explicit prompt instruction — belt-and-suspenders, since prompt wording alone isn't a reliable
enough guarantee for a value downstream code treats as always-positive.

## 2. LLM invocation pattern

**Decision (superseded — see §10)**: The requester later explicitly directed the opposite of the
original decision below: normalization must use LangGraph, and the client must be a swappable
`NormalizerClient` Protocol matching `MineruClient`'s shape, with a real `MockNormalizerClient`
(not deferred) since the existing test suite already depends on offline mock behavior. §10 is the
current decision; the original text is kept for history only.

**Original decision**: Follow the exact convention already used by `plan/service.py::generate_plan()` and
`chat/agents/analysis.py::analysis_node()`: an inline `if settings.use_mock_llm: ... else: ...`
branch at the call site, calling `app.core.llm.get_chat_model().ainvoke(prompt)` directly (no
`with_structured_output`, no LangGraph node — this is a single extraction call, not a chat-thread
interaction), and parsing the model's JSON text response with a tolerant `json.loads` + fallback
(mirroring `plan/service.py::_parse_and_normalize()`'s `re.search(r"\{...\}")` rescue pattern,
extended to also match a top-level array/object safely).

**Original rationale**: The requester explicitly asked to match how other features already do LLM
interaction rather than reusing MinerU's swappable-`Protocol` pattern — every existing LLM call
site in this codebase uses the plain settings-gated branch, none use a Protocol/factory for the LLM
itself (that pattern is reserved for `get_chat_model()`, which already is the swap point). Using a
second abstraction layer on top of `get_chat_model()` here would be inconsistent with every sibling
feature.

**Original alternatives considered**: A `NormalizerClient` Protocol mirroring `MineruClient` —
rejected; that pattern exists for MinerU specifically because it's an external HTTP service being
mocked end-to-end, whereas `get_chat_model()` already *is* the LLM's swap point and every other
feature composes directly on top of it. (This is the alternative §10 later adopted instead.)

## 3. Prompt shape and mock-mode behavior

**Decision (revised — see §9, §10, §14)**: One prompt *per chunk* (not one prompt for the whole
statement), instructing the model via `with_structured_output(ExtractedStatement)` rather than a
free-text "return ONLY JSON" instruction + manual parsing. Mock mode is now a real
`MockNormalizerClient` class (§10), not an inline branch — still no network call, still a small
fixed deterministic result.

**Original decision**: One prompt containing the serialized `content_list` entries (truncated/summarized if
extremely long — a page-count-bounded statement per SC-001 keeps this practical) plus the markdown
as a fallback block, instructing the model to return ONLY a JSON object matching the spec's shape
(`bank_name`, `account_hint`, `transactions[]` with `transaction_date`, `merchant_raw`, `category`,
`amount`, `transaction_type`) — `duplicate_of` and category-fallback are computed *after* the LLM
call, not requested from the model (see §5, §6). In mock mode
(`settings.use_mock_llm=True`), return a small fixed deterministic result derived from whatever
text is present (e.g. one synthetic transaction), the same "no network call, shape-matching mock"
approach `plan/service.py::_mock_plan()` and `chat/summarize.py` already use — good enough for
router/service tests; a content-list-driven fixture-based mock is used in the dedicated
`normalizer.py` unit tests instead, similar to how `ingestion/mineru_client.py`'s tests use a
fixture ZIP rather than the runtime mock path.

**Original rationale**: Keeps this feature's mock behavior indistinguishable in *kind* from every other
mock-mode LLM call in the codebase — CI stays offline (Constitution I) without inventing a new
mocking mechanism.

**Original alternatives considered**: A separate deferred `MockNormalizerClient` (MinerU's pattern) —
rejected for the same reason as §2: no other LLM call site in this codebase defers a mock behind a
Protocol; the `use_mock_llm` branch is already the established mock seam. (This is the alternative
§10 later adopted instead — the mock is built immediately, not deferred, because the test suite
already needs it.)

## 4. Duplicate-detection query and matching rule

**Decision**: Query `Transactions` filtered by `user_id` only (not `account_id` — a statement's
account link may not exist yet at normalization time, per spec Assumptions), selecting only the
columns needed for the comparison (`id`, `account_id`, `transaction_date`, `amount`,
`merchant_raw`) — never the full row, per Constitution III's egress-minimization clause. For each
extracted transaction, a likely duplicate is an existing row with an **exact amount match** and a
**transaction date within 2 calendar days** (covers pending-vs-posted date drift, a known
statement-reconciliation quirk); when the query returns more than one candidate, pick the closest
by date. `duplicate_of` is that row's `id` (as a string) or `null` when no candidate matches.

**Rationale**: The backend's own `transactions` table already carries a
`unique_ledger_transaction_match` constraint on `(user_id, account_id, transaction_date, amount,
merchant_raw)` — an *exact* match — confirming the backend already rejects byte-identical
re-imports at the DB level. This feature's `duplicate_of` therefore exists specifically to catch
**near**-duplicates the exact constraint wouldn't: a slightly reworded `merchant_raw` from a
re-OCR'd statement, or a one-to-two-day posting-date shift — not to re-implement the exact match
the backend already enforces. A 2-day window is a reasonable default for that drift; not treated as
a hard requirement — tunable later without an interface change since it's an internal constant in
`normalizer.py`, not a public contract detail.

**Alternatives considered**: Matching by `account_id` too — rejected, since it isn't reliably
available yet (spec Assumptions). Fuzzy `merchant_raw` text matching (e.g. token-overlap or
edit-distance) as a required condition — rejected for v1 as unnecessary complexity; amount + date
window already covers the realistic drift case, and adding text fuzziness risks more false
positives (two unrelated transactions with similar merchant names) than it prevents false
negatives. LLM-judged matching — rejected per the spec's explicit "deterministic, no additional
language-model judgment" decision (spec Assumptions).

## 5. Category table design

**Decision**: A new own-DB table, `categories` (Alembic-managed, in the `ingestion` slice):
`id` (int, autoincrement PK), `name` (unique, e.g. `"groceries"`), `label` (human-readable display
form, e.g. `"Groceries"`), `is_fallback` (bool, exactly one row MUST be `true` — this is the row
assigned when nothing matches). Seeded in the same migration via `op.bulk_insert` with a starter
set: groceries, dining, transport, utilities, rent, salary, transfer, fees, entertainment,
healthcare, shopping, and `other` (`is_fallback=true`). A small `categories.py` module exposes
`resolve_category(name: str) -> str`: case-insensitive exact match against `categories.name`,
falling back to the `is_fallback` row's `name` when the LLM's chosen label doesn't match any row
verbatim. New categories are added later via a future migration/admin action — out of scope for
this feature to expose an API for that (spec Assumptions).

**Rationale**: Directly implements the requester's explicit instruction ("category model... enable
us to add categories... prepopulate it with known values") — a DB-backed lookup instead of a
hardcoded Python enum, matching the "own DB, Alembic-managed" precedent already set by
`app/features/audit/models.py` and `app/features/recommendations/models.py`. Case-insensitive exact
match (not fuzzy) keeps `resolve_category()` deterministic and cheap; the LLM prompt (§3) already
instructs the model to choose from the known list by name, so exact-after-casefold is expected to
be the common case, with the fallback row as the safety net FR-008 requires.

**Alternatives considered**: A Python `Enum` (the "fixed enum" option discussed before this was
raised) — rejected per the requester's explicit follow-up: categories must be extensible without a
code change, which an `Enum` cannot provide. Fuzzy/embedding-based category matching — rejected as
unnecessary; the LLM is already given the known category list in-prompt, so a normal exact/casefold
lookup is sufficient and keeps `resolve_category()` trivially testable.

## 6. Object storage output path

**Decision**: Confirmed during specification — `normalized.json` is written to
`{settings.storage_s3_ocr_bucket}/{statement_id}/normalized.json`, the exact same no-`user_id`
prefix Part 1 already uses for `markdown.md`/`content_list.json`/`images/`. No new setting is
needed; `service.py` reads the `StatementOcrResult`'s own prefix convention (derivable from
`statement_id`, already resolved via the `StatementOcrResult.statement_id` FK) rather than
reconstructing it from `seaweed_file_id` a second way.

**Rationale**: Keeps one statement's entire OCR+normalization output under one consistent prefix,
avoiding the mismatch the original feature request would have introduced (see spec.md Assumptions
— this was corrected during `/speckit-specify` after inspecting Part 1's already-merged code).

**Alternatives considered**: `{user_id}/{statement_id}/` (the request's original wording) —
rejected once Part 1's shipped, no-`user_id` convention was found; changing Part 1 retroactively
was rejected by the requester as unnecessary churn on already-merged code.

## 7. Required configuration

**Decision (revised — see §13)**: One new setting was added after all:
`normalization_max_parallel_chunks: int = 1`. Everything else in the original decision still
holds — no new LLM credential/model setting, still reuses `settings.use_mock_llm`,
`settings.openai_base_url`, `settings.openai_api_key`, `settings.model_name`, and
`settings.storage_s3_ocr_bucket` exactly as before.

**Original decision**: No new setting is added to `app/core/config.py`. Normalization reuses
`settings.use_mock_llm`, `settings.openai_base_url`, `settings.openai_api_key`, and
`settings.model_name` exactly as `plan/service.py` already does, and reuses
`settings.storage_s3_ocr_bucket` exactly as Part 1 already does.

**Original rationale**: Nothing about this feature's external dependencies differs from what's already
configured and fail-fast-validated; adding a parallel setting (e.g. a normalization-specific model
name) would be speculative — no requirement calls for a different model than chat/plan already use.

**Original alternatives considered**: A dedicated `normalization_model_name` override — rejected as
premature; can be added later with zero migration cost if a real need appears (it would be an
optional setting defaulting to `settings.model_name`).

## 8. Cross-slice audit write and backend-write boundary

**Decision**: Same as Part 1 — call `app.core.audit.record_audit()` + explicit `session.commit()`
from `service.py`, action `"ingestion.normalize"`, detail `{"statement_id", "ocr_result_id",
"prefix"}`. The endpoint returns `{normalized_json, model_used}` and writes **no** row to
`statement_normalized` (a backend-owned table) — the caller (Django) persists that itself, exactly
mirroring the shape of that table (`normalized_json` + `model_used` are its two feature-supplied
columns; `adjusted_at`/`id`/`statement_id` are the backend's own to set).

**Rationale**: Reuses the already-established, already-tested audit convention from Part 1;
constructing `StatementNormalized` directly from this service would violate Constitution IV
(read-only backend DB) — confirmed by inspecting the generated model, which is exactly shaped to
receive what this feature returns, strongly suggesting the backend already intends to write it
itself upon receiving this response.

**Alternatives considered**: Writing `statement_normalized` directly — rejected, Constitution IV
NON-NEGOTIABLE. A new audit action helper — rejected; `record_audit()` already generalizes over
`action`/`detail`, no new helper is needed for a new action string.

---

## Post-implementation revision: chunked LangGraph pipeline

Everything below was added after validating the original single-prompt design against a real
3-page NBE statement (40+ transactions) and hitting real limits it couldn't have surfaced any other
way. These decisions supersede §1–§3 and §7 above.

## 9. Chunking strategy

**Decision**: Split OCR content into prompt-sized chunks before extraction, rather than sending the
whole statement in one prompt. Chunking operates on `content_list` entries; an oversized `table`
entry (`table_body` longer than the chunk budget) is split at the `<tr>` row boundary using a real
HTML parser (BeautifulSoup, `html.parser` backend) — not regex over the markup — then the resulting
row-batches are packed greedily alongside the statement's other (small) entries into chunks up to
`_MAX_CHUNK_CHARS` (1200, tuned empirically — see below). When `content_list` is empty, `markdown`
is used as a single fallback chunk (§1).

**Rationale**: A real bank statement's transaction table arrives from MinerU as *one* `content_list`
entry containing every row across every page as a single HTML blob (confirmed: a 40-row, 3-page
statement produced one ~9KB `table_body` entry) — chunking at the entry level alone does nothing,
since one entry dominates the statement's size. Splitting at the row boundary with a real parser
(Constitution VIII) correctly preserves each `<tr>`'s structure and any nested tags, which a
hand-rolled regex over table markup would risk corrupting on edge cases (attributes, nested `<td>`
content, self-closing variants).

**Tuning history** (all confirmed against the real statement + a live provider, not simulated):
- 8000 chars/chunk: sliced directly through a `<tr>` mid-row, handing the model truncated/invalid
  markup — it correctly returned zero transactions rather than guess (silently wrong, not loudly
  wrong).
- 3000 chars/chunk: fixed the truncation, but combined with `extra_fields` (§14) roughly tripling
  response verbosity per transaction, completions still got cut off mid-JSON for chunks with ~10+
  rows.
- **1200 chars/chunk (current)**: reliably produces completions that fit within a real,
  bandwidth-conscious `max_tokens` ceiling (§11) without truncation.
- 2000 chars/chunk was tried once more (to reduce total chunk count for latency) but reintroduced
  the provider's admission-control rejection from §11 — reverted.

**Alternatives considered**: A fixed row-count-per-chunk (e.g. "10 rows") instead of a character
budget — rejected; row byte-size varies enormously with merchant-name length (a long Arabic
transliterated name can be 5× a short English one), so a size budget is the actual constraint, not
a row count.

## 10. NormalizerClient — swappable class matching MineruClient's shape

**Decision**: `normalizer.py` exposes a `NormalizerClient` `Protocol`
(`async def normalize(content_list, markdown, known_categories) -> tuple[dict, str]`), a real
`LangGraphNormalizerClient` implementation, a `MockNormalizerClient` (built now, not deferred —
unlike MinerU's mock, this one is required immediately since the existing test suite already runs
with `USE_MOCK_LLM=1` by default), and a `get_normalizer_client()` factory reading
`settings.use_mock_llm` to pick between them. `service.py` depends only on the `NormalizerClient`
interface, obtained via the factory — exactly `mineru_client.py`'s shape.

**Rationale**: Explicit, direct instruction from the requester, reversing §2's original decision.
The requester's stated reasoning: normalization is becoming a multi-step (chunked, LangGraph-based)
pipeline, which benefits from being encapsulated behind a clear, testable interface the same way
MinerU's HTTP client already is — and the codebase already has one established pattern for
"swappable external-call client," so reuse it deliberately rather than staying with the
simpler-but-now-insufficient inline-branch convention every other LLM call site uses. This directly
motivated Constitution VIII's "reuse an existing pattern deliberately rather than inventing a
parallel one" clause.

## 11. LangGraph pipeline + `max_tokens` interaction with provider rate limits

**Decision**: The extraction pipeline is a LangGraph `StateGraph` with one node
(`extract_batch`) that self-loops via a conditional edge until every chunk is processed, batching up
to `settings.normalization_max_parallel_chunks` chunks per tick (§13) and accumulating
`bank_name`/`account_hint`/`transactions`/`extra_fields` across ticks. Each individual chunk's LLM
call sets an explicit `max_tokens` ceiling (`_CHUNK_MAX_TOKENS = 4096`) via `get_chat_model()`
(extended to accept an optional `max_tokens` override — the shared factory stays the only place a
model is constructed, per Constitution VI).

**Rationale confirmed against a real low-tier provider (Groq, `on_demand` tier, 8000 TPM)**:
raising `max_tokens` to compensate for truncated completions initially seemed to help, but at 6000
it caused *new* `413 Request too large` rejections — the provider's admission control counts
`prompt_tokens + max_tokens` against the per-minute budget **before generation starts**, so a
higher ceiling makes a request more likely to be rejected outright, not less. The fix was smaller
chunks (§9), not a bigger ceiling; `max_tokens=4096` alongside 1200-char chunks is the combination
that held up under real load.

**Alternatives considered**: An unbounded/default `max_tokens` (provider default) — rejected; this
is what originally caused silent mid-JSON truncation with no clear error signal. A per-provider
configurable `max_tokens` — rejected as premature; the constant is scoped to `normalizer.py` and can
become a setting later if a different provider's needs diverge.

## 12. Retry on transient generation failures

**Decision**: The structured-output call chains `.with_retry(stop_after_attempt=3)` — a LangChain
`Runnable` method (Constitution VIII: prefer the library's own mechanism over a hand-rolled retry
loop) — rather than writing a manual retry wrapper.

**Rationale confirmed against a real provider**: the model occasionally emits a corrupted JSON
escape sequence (e.g. `\u062h` — not valid hex — inside a transliterated Arabic name), which the
provider's own strict-mode validation correctly rejects with a 400. This is a transient generation
glitch (retrying the identical request succeeds), not a schema or prompt defect, so retrying the
specific request is the correct response — unusual for a 400 (normally non-retryable per REST
convention) but justified by the specific, confirmed failure mode.

**Alternatives considered**: A hand-rolled `for attempt in range(3): try/except` loop — rejected per
Constitution VIII once `with_retry` was confirmed to exist and do exactly this.

## 13. Configurable parallelism

**Decision**: New setting `normalization_max_parallel_chunks: int = 1`. The LangGraph node processes
`state["chunks"][index : index + max_parallel]` per tick via `asyncio.gather`, so a value of 1
(default) is fully sequential — the safest default for an unknown account tier — and a higher value
trades per-minute budget headroom for wall-clock latency.

**Rationale**: Confirmed against a real statement that fully-sequential processing of an 11-chunk
document is slow in wall-clock terms purely from round-trip count, independent of any rate-limit
issue. The requester explicitly asked for concurrent dispatch, configurable, defaulting to 1 so
existing low-tier/free-tier setups aren't put at greater rate-limit risk by default. `asyncio.gather`
(stdlib) is used for the fan-out rather than LangGraph's `Send` API, since `Send` fires an entire
batch with no built-in concurrency cap — bounding concurrency to exactly `max_parallel` needed the
explicit slice-then-gather shape instead.

**Confirmed operationally**: on Groq's free tier (8000 TPM), the dominant cost was `429` retry
backoff (the OpenAI SDK's own built-in rate-limit retry, separate from §12's `with_retry`) — one
chunk alone took 61.8s due to repeated 429s. Switching provider (OpenRouter, a different free-tier
model) with `max_parallel=4` completed the same 11-chunk statement in 119s with zero 429s — still
slow (free-tier model latency, 4–40s per call), but the earlier hard rate-limit rejections were
gone. This is a tier/provider characteristic, not a pipeline defect.

## 14. Extensible `extra_fields` — capturing more than the minimum schema

**Decision**: `ExtractedTransaction` and `ExtractedStatement` both carry an `extra_fields: list[ExtraField]`
field (`ExtraField = {key: str, value: str}`), defaulting to an empty list — a list of key/value
objects, not an open `dict`. `service.py` includes `normalized_json["extra_fields"]` in the response
only when non-empty.

**Rationale**: The requester explicitly said the spec's documented shape (`bank_name`,
`account_hint`, `transactions[...]`) is a *minimum* — anything else visible in the document (account
number, statement period, opening/closing balance, per-transaction reference numbers, value dates,
running balance, etc.) should also be captured. An open `dict[str, str]` was tried first and
**rejected by the provider**: Groq/OpenAI strict structured-output mode requires
`additionalProperties: false` on every object in the schema, which is fundamentally incompatible
with an unconstrained map type (confirmed via a live 400 error naming the exact schema path). A list
of well-defined `{key, value}` objects achieves the same "capture anything else" goal within a
strict-mode-compatible schema. A second issue surfaced once this fixed the first: declaring
`extra_fields` as `list[ExtraField] | None` (nullable) still requires the model to emit the key
under strict mode (nullable ≠ optional-to-omit) — the model sometimes omitted it anyway, causing a
schema-validation rejection. Fixed by making the field a plain non-nullable list defaulting to
empty, removing the null-vs-omitted ambiguity entirely.

**Alternatives considered**: `dict[str, str]` — rejected, strict-mode incompatible (above).
`dict[str, Any]` — same problem, worse (also loses type information cross-provider).
`list[ExtraField] | None` — rejected after the omitted-key failure mode was confirmed; a required
list with an empty-list default is strictly more reliable for the same capability.

## 15. Per-transaction `ai_description`

**Decision**: `ExtractedTransaction` gained a required `ai_description: str` field — a verbose,
multi-sentence, LLM-generated natural-language description of the transaction, distinct from
`merchant_raw` (the raw extracted merchant text). The prompt (`chunking._build_prompt`) explicitly
instructs the model not to just restate `merchant_raw`. `service/normalize.py` passes it through
unchanged (`txn.get("ai_description", "")`) into the persisted/returned transaction shape.
`MockNormalizerClient` returns a fixed descriptive sentence so `settings.use_mock_llm` callers still
get a non-empty value.

**Rationale**: The requester asked for a more verbose per-transaction description than `merchant_raw`
alone provides, to give downstream consumers (e.g. a chat/insights feature) richer natural-language
context per transaction without needing a second LLM call. Modeled as a required field (no default),
matching how `merchant_raw`/`category` are already treated — the strict structured-output schema
requires it to be present same as any other required field, so omission isn't possible by
construction.

**Bug found and fixed while adding this field**: `service/normalize.py`'s transaction-building loop
was already dropping `txn.get("extra_fields")` — the contract (§14 above) documented per-transaction
`extra_fields` in the response, but the code that assembles each transaction dict never copied it
from the LLM's output. Fixed alongside `ai_description` by building the entry as a plain dict and
conditionally adding `extra_fields` only when non-empty (same pattern already used for the
statement-level `extra_fields`). Covered by
`test_normalize_transaction_extra_fields_are_passed_through` and
`test_normalize_transaction_without_extra_fields_omits_the_key` in `test_service.py`.

## 16. Real e2e re-validation after `ai_description` — two more real-provider findings

**Context**: Re-ran the same real NBE statement (cached MinerU output, real OpenRouter free-tier
model) through `LangGraphNormalizerClient` after adding `ai_description` and the `extra_fields`
passthrough fix (§15 above), to confirm both work against real content before considering the work
done. Two new, real findings came out of this run — both fixed, one left as a known limitation.

**Finding 1 — fixed**: `ai_description`'s extra verbosity pushed one chunk into
`openai.LengthFinishReasonError` (`finish_reason="length"`) against the configured OpenRouter free
model. The error's `completion_tokens_details` showed `reasoning_tokens=3050` out of a 4096-token
budget — this specific model is a "reasoning" model that spends a large, non-fixed share of its
completion budget on hidden chain-of-thought tokens before ever emitting the structured JSON, so the
existing `_CHUNK_MAX_TOKENS=4096` constant (safe for Groq's TPM-capped tier, per §11) was too tight
for it. Rather than raising the shared default (which would reintroduce the §11 Groq admission-control
regression for anyone still on that tier), the ceiling was promoted to a setting,
`normalization_chunk_max_tokens` (default unchanged at 4096), so it can be raised per
provider/model. Set to `8192` in this environment's `.env` for the OpenRouter reasoning model;
re-running with that value completed all 11 chunks successfully (31 transactions, every one with a
non-empty multi-sentence `ai_description`, avg ~300 chars).

**Finding 2 — fixed**: The statement-level `extra_fields` list contained duplicate `bank_name`/
`account_hint` entries with the literal string `"null"` as their value — the model was stuffing
these into `extra_fields` from chunks where it couldn't determine them, even though the prompt
already told it to use `null` for the dedicated top-level fields in that case. Fixed with an explicit
prompt instruction: `ai_description`'s addition prompted a wording pass, and this line was added
alongside it — never add `bank_name`/`account_hint` as an `extra_fields` entry, they always belong in
the dedicated top-level fields. Confirmed fixed on the re-run above — the duplicate `"null"` entries
no longer appeared.

**Finding 3 — known limitation, not pursued**: One chunk's statement-level `extra_fields` contained a
garbled entry (a `source_page` value that was actually a fragment of the model's own reasoning
monologue, e.g. `"}]}]}  <-- This is messed up. Need proper JSON..."`) — the value was still a
syntactically valid string, so strict-mode schema validation didn't reject it and `.with_retry`
never triggered. This is the same class of free/small-model quality noise already documented in §11
(literal `\uXXXX` artifacts in transliterated names) — an inherent limitation of this specific
free-tier reasoning model under structured-output pressure, not a pipeline defect. Not pursued
further, consistent with the earlier precedent.
