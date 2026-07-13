# Data Model: Statement Transaction Normalization

This feature reads three existing backend-owned models, writes one new own-DB table (plus its
seed data), writes one audit row, and writes one object-storage blob. It writes no backend-owned
row.

## Entities read (existing, read-only)

### `StatementOcrResult` (`app/backend_db/models/statements.py`)

The input identifier this feature's endpoint accepts.

| Column | Type | Used for |
|---|---|---|
| `id` | UUID | Looked up by the caller-supplied `ocr_result_id` |
| `statement_id` | UUID | Locates the OCR output prefix (`{bucket}/{statement_id}/`) and the parent `StatementFiles` row |

### `StatementFiles` (existing)

Read via `StatementOcrResult.statement_id` for its `user_id` — needed to scope the duplicate-match
query (§ below). No other column is read.

### `Transactions` (existing)

Read for duplicate matching only. Per Constitution III egress-minimization, only these columns are
ever selected — never the full row:

| Column | Type | Used for |
|---|---|---|
| `id` | UUID | Returned as `duplicate_of` when matched |
| `user_id` | UUID | Query filter |
| `account_id` | UUID | Not filtered on (may not be known yet for the new statement) but read for completeness of the match record |
| `transaction_date` | date | Compared within a 2-day window (research.md §4) |
| `amount` | numeric | Compared for an exact match (research.md §4) |
| `merchant_raw` | str? | Not used as a match condition in v1 (research.md §4); read for potential future use, not egressed further |

No column of any of these three models is ever written by this feature (Constitution IV).

## Entities written

### `Category` (**NEW**, `app/features/ingestion/categories.py`, own DB, Alembic-managed)

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK, autoincrement | |
| `name` | str, unique, not null | Lowercase, machine-matched key (e.g. `"groceries"`) |
| `label` | str, not null | Human-readable display form (e.g. `"Groceries"`) |
| `is_fallback` | bool, not null, default `false` | Exactly one row MUST be `true` — assigned when no category matches (FR-008) |

Seeded by its own migration (not a runtime write) with a starter set (research.md §5): groceries,
dining, transport, utilities, rent, salary, transfer, fees, entertainment, healthcare, shopping,
and `other` (`is_fallback=true`).

### `AiAuditLog` (existing, own DB, already migrated)

One row per normalization call, via `app.core.audit.record_audit()` + explicit commit (same
pattern as Part 1):

| Column | Value this feature supplies |
|---|---|
| `user_id` | `None` (no authenticated end-user context — caller is the backend) |
| `action` | `"ingestion.normalize"` |
| `detail_json` | JSON string: `{"statement_id", "ocr_result_id", "prefix"}` |

## Non-relational data this feature handles

| Conceptual entity | Representation | Where it lives |
|---|---|---|
| **Source OCR content** | `content_list.json` entries + `markdown.md` text | Read from `{bucket}/{statement_id}/` (Part 1's output), never rewritten |
| **Normalized result** | JSON object: `{bank_name, account_hint, transactions: [...], extra_fields?: [...]}` | Written to `{bucket}/{statement_id}/normalized.json`; also returned to the caller |
| **`NormalizeStatementResult`** | Pydantic response model: `{normalized_json: dict, model_used: str}` | Returned to the caller, not persisted as its own row |

### `transactions[]` entry shape (within the normalized JSON)

| Field | Type | Notes |
|---|---|---|
| `transaction_date` | `YYYY-MM-DD` string | Omitted from the list entirely if not confidently determinable (spec Edge Cases), not guessed |
| `merchant_raw` | string | As extracted from source content |
| `ai_description` | string | LLM-generated, verbose multi-sentence natural-language description of the transaction — deliberately more detailed than `merchant_raw`, not a restatement of it (research.md §15) |
| `category` | string | Always one of `Category.name`'s seeded values — resolved via `resolve_category()` (research.md §5), never free text |
| `amount` | number | Always a positive magnitude — direction is `transaction_type`, not sign (research.md §1, confirmed against a real model) |
| `transaction_type` | `"debit" \| "credit" \| "fee" \| "transfer"` | |
| `duplicate_of` | UUID string or `null` | Set via the deterministic match against `Transactions` (research.md §4) |
| `extra_fields` | `[{key, value}]`, omitted from a `transactions[]` entry when empty | Any other per-transaction data the source visibly contains beyond the minimum shape (e.g. reference number, value date, running balance) — see research.md §14 |

### Statement-level `extra_fields` (top of the normalized JSON, sibling of `transactions`)

Same `[{key, value}]` shape as above, one level up — captures statement-level facts beyond
`bank_name`/`account_hint` (e.g. account number, currency, statement period, opening/closing
balance). Present in `normalized_json` only when non-empty (research.md §14).

## Validation rules

- `ocr_result_id` (request input) MUST parse as a UUID; a non-UUID value is a client error (422,
  enforced by typing the request field as `UUID` rather than `str`), matching Part 1's precedent
  (FR-016) — distinct from a well-formed-but-unknown UUID (404, FR-002).
- A `transactions[]` entry missing a confidently-determined `transaction_date` or `amount` MUST be
  omitted from the result entirely (spec Edge Cases) rather than included with a null/guessed
  value.
- `category` MUST always resolve to one of `Category.name`'s current values — `resolve_category()`
  guarantees this by construction (falls back to the `is_fallback` row rather than ever returning
  an unrecognized string).
- No `validate_storage_key()` call is required for the read or write paths here — both are built
  from the already-validated `statement_id` (a UUID looked up via a trusted backend DB row), the
  same trust tier established in Part 1's data-model.md.

## State / lifecycle

Same all-or-nothing shape as Part 1: one normalization request either returns a complete
`NormalizeStatementResult` (the object is persisted, one audit row written) or an explicit failure
with nothing new persisted (FR-014). Re-normalizing the same `StatementOcrResult` id overwrites the
existing `normalized.json` at its prefix — no versioning in v1 (spec Assumptions).
