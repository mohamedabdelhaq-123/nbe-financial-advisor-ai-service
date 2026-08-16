# Data Model: Normalizer Pipeline Rework

This feature changes the shape of data already flowing through the existing statement-normalization
feature (spec 005) — no new backend-owned or own-DB tables, no migration. It changes: the LLM-facing
extraction schema, the `NormalizerClient` interface, the response/storage JSON shape, and how a
statement's content is portioned before extraction.

## Entities read (existing, unchanged)

Same as spec 005 data-model.md: `StatementOcrResult`, `StatementFiles` (for `user_id`), `Transactions`
(duplicate-match columns only), `Category` (own DB, for `resolve_category()`). This feature adds no
new read.

## LLM-facing extraction schema (`normalizer/schemas.py`)

### `ExtractedTransaction` (changed)

| Field | Type | Change |
|---|---|---|
| `transaction_date` | `str` (`YYYY-MM-DD`) | unchanged |
| `merchant_raw` | `str` | unchanged |
| `ai_description` | `str` | unchanged |
| `category` | `str` | unchanged |
| `amount` | `float` (positive magnitude) | unchanged |
| `transaction_type` | `Literal["debit","credit","fee","transfer"]` | unchanged |
| `balance` | `float \| None` | **new** — running balance for this row, when stated (FR-003) |
| `merchant_normalized` | `str \| None` | **new** — canonicalized merchant name, distinct from `merchant_raw` (FR-003) |
| `extra_fields` | `list[ExtraField]` | unchanged shape — still the strict-mode-compatible list-of-pairs form; converted to a dict only at the service boundary (Decision 1) |

### `ExtractedStatement` (changed)

| Field | Type | Change |
|---|---|---|
| `bank_name` | `str \| None` | unchanged |
| `account_hint` | — | **removed**, replaced by `account_number` |
| `account_number` | `str \| None` | **new** — the real, unmasked account number as printed in the source (FR-002) |
| `transactions` | `list[ExtractedTransaction]` | unchanged shape, changed element type (above) |
| `extra_fields` | `list[ExtraField]` | unchanged shape (Decision 1) |

### `ExtraField` — unchanged (`{key: str, value: str}`)

### `NormalizerClient` Protocol (changed)

```python
class NormalizerClient(Protocol):
    async def normalize(
        self,
        content_list: list,
        markdown: str,
        known_categories: list[str],
        *,
        statement_id: str,
        ocr_result_id: str,
    ) -> tuple[dict, str]: ...
```

`statement_id`/`ocr_result_id` are **new, required keyword-only parameters** — both already resolved
in `service/normalize.py` before the extraction call, threaded through purely so the extraction call
site can stamp them as `RunnableConfig` metadata (FR-012). Every implementer (`LangGraphNormalizerClient`
→ renamed `ChunkedLangGraphNormalizerClient`, `MockNormalizerClient`) must accept and (for the real
implementation) use them; the mock accepts and ignores them, matching its existing no-op-on-extra-input
posture.

## Response / storage JSON shape (`service/normalize.py` output — the actual contract boundary)

This is what changes for the caller (Django backend) and what's written to `normalized.json`:

```jsonc
{
  "bank_name": "National Bank of Egypt",
  "account_number": "4213010248203200016",           // was account_hint (masked); now real, unmasked
  "transactions": [
    {
      "transaction_date": "2026-05-01",
      "merchant_raw": "Carrefour #abc123",
      "merchant_normalized": "Carrefour",              // new
      "ai_description": "...",
      "category": "groceries",
      "amount": 1234.56,
      "transaction_type": "debit",
      "balance": 4809.31,                               // new
      "duplicate_of": null,
      "extra_fields": {                                  // was a [{key, value}] list; now a map
        "reference_number": "421IPNM243040054",
        "value_date": "2026-05-01"
      }
    }
  ],
  "extra_fields": {                                       // was a [{key, value}] list; now a map
    "opening_balance": "24.57"
  }
}
```

`extra_fields` (both levels) is present only when non-empty — unchanged rule, just a changed
container type (dict instead of list).

## Extraction portion (chunk) — sizing changed, shape unchanged

Still `list[dict]` — a slice of `content_list` entries. What changes is *how the slice boundary is
chosen* (research.md §5): primarily by estimated transaction-row count for `table` entries (derived
from `normalization_chunk_max_tokens` / `normalization_est_tokens_per_row`), with the existing
character-length ceiling demoted to a fallback safety net rather than the primary driver, and applied
liberally (not row-capped) to non-`table` entries.

## New configuration (`app/core/config.py`, `ChatModelSettings`)

| Setting | Type | Default | Purpose |
|---|---|---|---|
| `normalizer_strategy` | `Literal["chunked_langgraph"]` | `"chunked_langgraph"` | Selects the active `NormalizerClient` implementation (FR-010) — one member today, the documented swap point for a future second strategy. |
| `normalization_est_tokens_per_row` | `int` (`gt=0`) | `450` | Estimated output tokens per extracted transaction row; drives the FR-007 row-cap formula (research.md §5). |

`normalization_max_parallel_chunks` and `normalization_chunk_max_tokens` (existing, spec 005) are
reused unchanged — the former now feeds `config={"max_concurrency": ...}` instead of a manual batch
slice size; the latter now also feeds the row-cap formula in addition to its existing per-call
`max_tokens` role.

## Validation rules (new/changed vs. spec 005)

- `account_number` is never masked, truncated, or redacted by this service at any point (FR-002) —
  contrasts with spec 005's `account_hint`, which was already documented as "best-effort masked."
- `extra_fields` (both levels) MUST be a JSON object in the response/storage output, never a JSON
  array, and MUST be omitted (not an empty object) when there are no facts to report — same
  omit-when-empty rule as before, changed container type only.
- `balance`/`merchant_normalized` follow the same "omit rather than guess" rule already established
  for `transaction_date`/`amount` (spec 005 data-model.md) — `null`/absent when not confidently
  determinable, never a placeholder.
- `normalization_est_tokens_per_row` MUST be `> 0` (fail-fast at config load, Constitution VII) —
  a zero/negative value would make the row-cap formula produce zero or a negative row count.
- The row-cap formula MUST always yield at least 1 (`max(1, ...)`) — a single oversized row must still
  be attempted, never produce a zero-size chunk (FR-008's fallback ceiling is the actual backstop for
  that case).

## State / lifecycle

Unchanged from spec 005: one normalization request either returns a complete result (object
persisted, one audit row written) or fails outright with nothing new persisted — FR-016 makes this
explicit for the new concurrent execution path specifically (no partial-portion persistence even when
some portions succeeded before a later one exhausted its retries).
