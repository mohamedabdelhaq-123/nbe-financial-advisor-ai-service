# Phase 0 Research: Normalizer Pipeline Rework

## 1. `extra_fields` shape: dict at the boundary, list-of-pairs stays the LLM contract

**Decision**: Keep `ExtraField` (`{key, value}`) as the *LLM-facing* structured-output schema — strict
structured-output mode still requires it (spec 005 research.md §14: `additionalProperties: false` on
every object rules out an open `dict`). Convert the list to a plain `dict[str, str]` exactly once, in
`service/normalize.py`, immediately after the extraction call returns, before it's assembled into
`normalized_json`. Both the API response and the persisted `normalized.json` blob therefore carry a
map, never a list — matching `Transactions.extra_fields`'s real JSONB-as-dict column shape (FR-001).

**Rationale**: The list-of-pairs shape exists solely because of a provider constraint on the model's
*output* format; there's no reason that constraint should leak into what this service *returns*. One
conversion point, right after the LLM boundary, keeps the constraint fully contained.

**Alternatives considered**: Changing `ExtraField` itself to a dict — rejected, breaks strict-mode
structured output (confirmed failure mode in spec 005). Converting at the Django/backend side instead
— rejected per FR-001, which places this requirement on this service, not the consumer.

## 2. `account_number`: real value, replaces `account_hint`

**Decision**: Rename `ExtractedStatement.account_hint` → `account_number: str | None`. The prompt
instructs the model to transcribe the account number exactly as printed, never masked/truncated/
redacted. No masking logic is added anywhere in this service (per the requester's explicit "it
wouldn't make sense" direction).

**Rationale**: Directly implements FR-002. `BankAccounts` (backend) has no bare "hint" concept —
`masked_account_number` is a *display* form the backend itself derives; giving the backend the real
value is what makes account matching/linkage possible at all (User Story 2).

**Alternatives considered**: Keeping `account_hint` alongside a new `account_number` — rejected;
FR-011 already treats this as a coordinated breaking change, so carrying both fields forward would
just create two sources of truth for the same fact with no consumer needing the old one.

## 3. `balance` and `merchant_normalized`: promoted to dedicated `ExtractedTransaction` fields

**Decision**: Add `balance: float | None` (running balance, when stated for that row) and
`merchant_normalized: str | None` (canonical merchant name, distinct from `merchant_raw`) to
`ExtractedTransaction`. Both optional — omitted/`null` when not determinable, never guessed (same
convention as `bank_name`/`account_number`).

**Rationale**: Directly implements FR-003 (requester's choice A). Both have dedicated, real columns
on the backend's `Transactions` table (`balance`, `merchant_normalized`) that today's `extra_fields`
grab-bag obscures — a running balance is one of the most standard bank-statement columns there is,
and folding it into a generic key-value collection makes it harder for the backend to use reliably.

**Alternatives considered**: Leaving both in the general `extra_fields` map from Decision 1 — rejected
per the requester's explicit choice; a key name in an open map isn't a stable contract the same way a
typed field is.

## 4. Content presentation: per-entry-type markdown rendering, not JSON+HTML

**Decision**: Replace `_build_prompt`'s `json.dumps(chunk)` with a renderer
(`agents/chunked_langgraph/markdown_render.py`) that converts each `content_list` entry to plain
text/markdown based on its `"type"`, per the schema the requester supplied (source:
`mineru/backend/pipeline/pipeline_middle_json_mkcontent.py::make_blocks_to_content_list()`):

| `type` | Rendering |
|---|---|
| `text` | The `text` field verbatim; rendered as a Markdown heading (`#` × `text_level`) when `text_level` is present, otherwise a plain paragraph. |
| `header` / `footer` / `page_number` / `aside_text` / `page_footnote` | The `text` field verbatim, as a plain paragraph — these carry statement metadata (e.g. page footers stating account/period info) that's worth keeping, not discarding as boilerplate. |
| `list` (`sub_type: ref_text`) | `list_items` as a Markdown bullet list. |
| `equation` | `text` (LaTeX) verbatim when present; entry contributes nothing when only `img_path` is set (no OCR text to extract — consistent with the existing "images not consulted" assumption, spec 005). |
| `image` | `image_caption` + `image_footnote` (joined) and `content` (in-image OCR text) rendered as plain text, in that order, when present; contributes nothing when all three are empty. |
| `table` | `table_caption` rendered before, `table_footnote` after, as plain text; `table_body` kept as **verbatim HTML** — Markdown natively supports embedded HTML tables, so no lossy HTML→pipe-table conversion is needed (this also keeps `chunking.py`'s existing row-boundary splitting, which already parses this same HTML with BeautifulSoup, working unchanged on the same field). |
| `chart` | Same treatment as `image` (`chart_caption`/`chart_footnote`/`content`); `content` is documented as always empty today, so this branch is currently a no-op in practice but stays correct if a future MinerU version populates it. |
| `code` | `code_body` in a fenced block tagged with `sub_type` as the language, plus caption/footnote as plain text. |
| any other/unrecognized `type` | Defensive fallback: render a `text`-shaped field if the entry happens to have one, else contribute nothing — logged at debug level. Satisfies the spec's edge case ("included in a plain, readable textual form... rather than dropped") for the case where there's actually text to include, without inventing content when there isn't any. |

`page_idx`/`bbox` are never rendered — positional metadata with no extraction value once content is
already ordered and chunked.

**Rationale**: Directly implements FR-004. This is the "best of both worlds" resolution to spec 005's
own §1 tension (sending both `content_list` and `markdown` doubled token usage for no benefit): the
structure comes from `content_list`'s pre-parsed entries, the presentation is markdown's native,
LLM-familiar syntax — with tables kept as real HTML rather than forced into a lossy pipe-table
conversion, since GitHub-flavored/CommonMark renderers (and LLMs trained on web-scale markdown) both
already handle embedded HTML tables natively.

**Alternatives considered**: Converting `table_body` to pipe-table syntax — rejected per the
requester's explicit correction; loses fidelity on merged cells/colspan with no offsetting benefit
once HTML-in-markdown is confirmed to work. Dropping caption/footnote fields as "just metadata" —
rejected; a table footnote stating e.g. "balance brought forward" is exactly the kind of statement
fact FR-003/Decision 1 are trying to capture reliably, not noise to discard.

## 5. Chunking: transaction-row-count primary, character ceiling as fallback only

**Decision**: For `table` entries specifically, cap the number of `<tr>` rows packed into one
extraction portion, derived from the configured output-token budget rather than a fixed magic
constant:

```
max_rows_per_chunk = max(1, floor(0.7 * normalization_chunk_max_tokens / normalization_est_tokens_per_row))
```

`normalization_est_tokens_per_row` is a new setting (default `450` — informed by spec 005's own
observed output composition: ~300-char `ai_description` (~75-110 tokens) + short typed fields + a
`balance`/`merchant_normalized` addition + variable `extra_fields` + JSON structural overhead). The
0.7 safety margin mirrors spec 005 research.md §16's finding that a reasoning-model backend can spend
a large, non-fixed share of its budget on hidden reasoning tokens before emitting JSON. Non-`table`
entries (text/header/footer/list/etc.) are **not** counted against this row cap — they don't scale
extraction output the way transaction rows do — and instead pack liberally under the existing
character-length fallback ceiling (renamed `_MAX_PORTION_CHARS`, same mechanism as today's
`_MAX_CHUNK_CHARS`), which also remains the safety net for a single pathologically large row (FR-008).

**Rationale**: Directly implements FR-007/FR-008/FR-009. Output risk (truncated/cut-off completions)
scales with transaction-row count, not with the character length of the source markup — a long
transliterated merchant name inflates the old character-count proxy without inflating actual output
much at all (and `json.dumps`'s default `ensure_ascii=True` inflated that proxy further, a distortion
this design sidesteps entirely by not measuring JSON-serialized length as the primary driver anymore).
Deriving the cap from the configured token budget, rather than hardcoding a number, means raising
`normalization_chunk_max_tokens` for a different model (as spec 005 §16 already did once, for a
reasoning model) automatically raises the row cap too, instead of requiring a second, unrelated
constant to be re-tuned by hand.

**Confirmed default value**: `0.7 * 4096 / 450 ≈ 6.37 → 6` rows per chunk at today's defaults —
deliberately conservative, smaller than the ~8-12 rows/chunk the old 1200-char default empirically
landed on. This is a reasoned starting point, not a re-validated one; **quickstart.md's real-statement
validation step MUST re-confirm it against a live model**, the same way spec 005's original char-based
constant was empirically tuned rather than assumed correct on the first try (research.md §9 "Tuning
history").

**Alternatives considered**: A real tokenizer (e.g. `tiktoken`) estimating exact prompt/output tokens
— rejected as unnecessary complexity for this pass; row-count already targets the actual output-risk
driver directly, and adding a token-estimation dependency is exactly the kind of speculative
complexity Constitution VIII cautions against absent a demonstrated need. Can be revisited later if
row-count alone proves insufficiently precise.

## 6. LangGraph-native fan-out: `Send` + reducers + `max_concurrency`, replacing the batch-tick loop

**Decision**: Replace `graph.py`'s single self-looping `extract_batch` node with:
- One `extract_chunk` node processing exactly one chunk.
- A dispatcher (conditional edge from `START`) emitting one `Send("extract_chunk", {...})` per chunk
  — LangGraph's documented dynamic map-fan-out pattern.
- State fields `transactions: Annotated[list, operator.add]` / `extra_fields: Annotated[list, operator.add]`
  so concurrent branch results merge automatically (no manual accumulation loop).
- `graph.ainvoke(state, config={"max_concurrency": settings.chat_model.normalization_max_parallel_chunks})`
  — reuses the existing setting/semantics unchanged (FR-005/FR-006), now enforced by LangGraph's own
  `asyncio.Semaphore`-backed executor (confirmed by reading `langgraph/pregel/_executor.py` directly:
  `if max_concurrency := config.get("max_concurrency"): self.semaphore = asyncio.Semaphore(max_concurrency)`)
  instead of a hand-rolled `chunks[index:index+max_parallel]` slice-and-gather loop.

`.with_retry(stop_after_attempt=3)` stays on the structured-output `Runnable` at the LLM-call level
(unchanged from spec 005 §12) — the thing being retried is specifically the structured-output call,
not the surrounding node logic, so retrying at that scope stays more precise than LangGraph's
node-level `RetryPolicy` (which exists — confirmed via `langgraph.types.RetryPolicy` — but would retry
the whole node body, a coarser scope than needed here).

**Rationale**: Directly implements FR-005/FR-006 via a library-native mechanism (Constitution VIII)
instead of the hand-rolled batch-tick loop, which also removed the "whole batch waits for its slowest
member" inefficiency (a semaphore-bounded pool starts a new chunk the instant a slot frees, rather
than at fixed batch boundaries). `bank_name`/`account_number` resolution ("first non-null wins") still
needs to happen in a reducer too, since multiple concurrent branches can each set/not-set it —
implemented as a small custom reducer function (`lambda old, new: old or new`) rather than the default
`operator.add`, which doesn't apply to a scalar `str | None` field.

**FR-016 (all-or-nothing failure) — confirmed, no extra code needed**: An unhandled exception raised
inside any `Send`-dispatched branch propagates out of `graph.ainvoke()` exactly like an exception in
the old sequential loop did — LangGraph does not swallow or partially-succeed a superstep by default.
This is exactly the semantics FR-016 requires, so it's a property to verify with a test, not something
that needs new guard code.

**Alternatives considered**: Keeping the hand-rolled batch-tick loop and only changing its batch size
— rejected; doesn't address the "not LangGraph-native" finding, and the semaphore-based approach
strictly dominates it (same concurrency cap, less wall-clock waste, less hand-rolled state-merge code).

## 7. Package split: shared contract vs. per-strategy `agents/` subpackage

**Decision**: `normalizer/` keeps only strategy-agnostic code at its root: `schemas.py` (the
`NormalizerClient` Protocol + `Extracted*` models — the contract every strategy must satisfy),
`mock.py` (a contract-level double, not a strategy), `duplicates.py` (post-extraction enrichment that
applies regardless of which strategy produced the data), and `__init__.py`'s factory. Everything
specific to *how* today's one strategy extracts data — `graph.py`, `chunking.py`,
`markdown_render.py`, `prompts.py`, `prompt_templates/` — moves into `normalizer/agents/
chunked_langgraph/`. `get_normalizer_client()` dispatches on a new setting,
`normalizer_strategy: Literal["chunked_langgraph"] = "chunked_langgraph"`, instead of only a mock/real
bool — a `Literal` with one member today, but the actual swap point FR-010 requires, matching how
`get_chat_model()` is already the one swap point for the LLM itself.

**Rationale**: Directly implements FR-010/User Story 5. `duplicates.py` living inside `normalizer/`
was previously questioned as inconsistent with `categories.py` living at the `ingestion/` root — this
split resolves that cleanly: both are strategy-agnostic post-extraction enrichment, so both belong
where every strategy can reach them, which this layout already provides without moving either file
relative to where they were flagged. Prompt content, by contrast, is inherently strategy-specific (a
different future strategy would need an entirely different prompt), so it belongs inside the owning
strategy's subpackage, not shared — reversing an earlier (pre-multi-strategy) suggestion to match
`chat`/`plan`'s single-strategy "prompts at feature root" convention.

**Alternatives considered**: A flat `normalizer/` with strategy files distinguished only by naming
convention (e.g. `graph_chunked_langgraph.py`) — rejected; doesn't scale file-size discipline the same
way (the requester's explicit "avoid large files" direction), and doesn't give a new strategy its own
prompt_templates/ directory without an awkward shared-directory naming scheme.

## 8. Observability: business-context metadata at the extraction call site

**Decision**: `NormalizerClient.normalize()` gains two required keyword-only parameters,
`statement_id: str` and `ocr_result_id: str` (threaded from `service/normalize.py`, where both are
already in scope). Inside `extract_chunk`, the structured-output call is invoked with
`config={"metadata": {"statement_id": ..., "ocr_result_id": ..., "chunk_index": ..., "prompt_version": ...},
"tags": [f"ingestion.normalize.chunk:{chunk_index}"]}`. `prompt_version` is computed once, at
prompt-template load time in `agents/chunked_langgraph/prompts.py`, as a short content hash
(`hashlib.sha256(template_source.encode()).hexdigest()[:8]`) of the Jinja2 template's rendered source
— additive to the existing git-committed template file, not a replacement for it (FR-013).

**Rationale**: Directly implements FR-012/FR-015. This service's existing OTel auto-instrumentation
(spec 013) already captures every LangChain/LangGraph call process-wide with zero call-site changes —
what it can't know on its own is business context specific to *this* call (which statement, which
chunk). `RunnableConfig.metadata`/`tags` is the existing, documented LangChain mechanism instrumented
spans already read from (confirmed via Langfuse's own LangChain integration docs), and — unlike the
per-feature attribution problem spec 013 §7 deliberately avoided solving via per-call-site config
(which would have meant touching every feature) — this is exactly one call site inside one
already-encapsulated function, so it doesn't reintroduce that cross-feature wiring burden.

**Open item confirmed empirically, not from docs alone**: Whether `Send`-dispatched concurrent
branches produce spans correctly nested under one parent trace (rather than fragmenting into
apparently-unrelated traces, which FR-015 forbids) could not be conclusively confirmed from Langfuse's
own documentation during planning — their LangChain/LangGraph integration page didn't specifically
address concurrent branch nesting. Python's `asyncio` propagates the current `contextvars` context
(which is where OTel's active-span context lives) to every new `Task` at creation time, which is the
mechanism `Send`-dispatched branches rely on, so this is *expected* to work correctly — but
**quickstart.md's validation step MUST verify this against a real statement and a real Langfuse
instance** before this is treated as confirmed, not merely asserted from how `asyncio` context
propagation is generally documented to behave.

**Alternatives considered**: Migrating prompt storage into Langfuse's own hosted Prompt Management —
rejected; no documented pattern supports "git is source of truth, Langfuse is a pure reference layer"
(confirmed via the `langfuse` skill's documentation search), and migrating would reverse this
codebase's very recent, deliberate Jinja2-externalization decision without a stated need to.

## 9. FR-011 (breaking contract change): process dependency, not a code deliverable

**Decision**: This plan's tasks are scoped to the AI service repository only. FR-011's requirement —
that the output-shape change ships as a coordinated update with the backend, not a silent shape change
— is recorded here as an explicit **cross-repository dependency** that must be tracked (e.g. linked
issue/PR on the backend side) alongside this feature's own PR, not solved by adding compatibility code
in this repository (the Clarifications session's answer B explicitly ruled out dual-shape support).

**Rationale**: This repository has no visibility into or control over the backend's deployment
sequencing; documenting the dependency explicitly (here, and again in tasks.md) is the correct scope
for a plan that can only guarantee its own side of a two-repository breaking change.

## 10. Telemetry redaction gap: tracked, not solved, in this feature

**Decision**: No redaction-pattern change ships as part of this feature (Clarifications Q1, answer B).
`tasks.md` MUST include an explicit tracking task (a code comment/TODO in the metadata-attaching call
site referencing this plan, plus a recommendation to open a separate backlog item) so the gap
identified during Constitution Check remains visible rather than disappearing once this feature's own
scope is marked done.

**Rationale**: Matches the requester's explicit scoping decision while satisfying the constitution's
governance requirement that "unavoidable deviations MUST be justified explicitly" — justified and
tracked, not silently absent.
