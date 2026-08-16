# Contract: `POST /internal/ingestion/normalize` (revised)

Supersedes the response shape documented in `specs/005-statement-normalization/contracts/
ingestion-normalize.md`. **Request shape, endpoint path, auth, and all failure-status behavior are
unchanged** — only `normalized_json`'s internal shape changes. This is a **breaking change** (FR-011)
requiring a coordinated update on the backend's consuming side (research.md §9) — not a
version-negotiated or dual-shape response.

## Request — unchanged

```
POST /internal/ingestion/normalize
Authorization: Bearer <AI_SERVICE_TOKEN>
Content-Type: application/json
```

```json
{
  "ocr_result_id": "9c2b7a1e-....-uuid"
}
```

## Response — success (200) — CHANGED

```json
{
  "normalized_json": {
    "bank_name": "National Bank of Egypt",
    "account_number": "4213010248203200016",
    "transactions": [
      {
        "transaction_date": "2026-05-01",
        "merchant_raw": "Carrefour #abc123",
        "merchant_normalized": "Carrefour",
        "ai_description": "A grocery purchase at a Carrefour supermarket, likely a routine household shopping trip based on the amount and merchant category.",
        "category": "groceries",
        "amount": 1234.56,
        "transaction_type": "debit",
        "balance": 4809.31,
        "duplicate_of": null,
        "extra_fields": {
          "reference_number": "421IPNM243040054",
          "value_date": "2026-05-01"
        }
      }
    ],
    "extra_fields": {
      "opening_balance": "24.57"
    }
  },
  "model_used": "gpt-4o-mini"
}
```

| Field | Type | Notes | Change vs. spec 005 |
|---|---|---|---|
| `normalized_json` | object | Also written verbatim to `{bucket}/{statement_id}/normalized.json` | unchanged storage convention |
| `normalized_json.bank_name` | string or `null` | Best-effort | unchanged |
| `normalized_json.account_number` | string or `null` | The account number **exactly as it appears in the source document** — never masked, truncated, or redacted; `null` when not determinable | **renamed from `account_hint`; no longer masked** |
| `normalized_json.transactions` | array | Zero or more; empty array is a valid, successful result | unchanged |
| `transactions[].transaction_date` | string (`YYYY-MM-DD`) | Omitted entirely if not confidently determinable | unchanged |
| `transactions[].merchant_raw` | string | As extracted | unchanged |
| `transactions[].merchant_normalized` | string or `null` | Canonicalized merchant name, distinct from `merchant_raw`; `null` when not determinable | **new field** |
| `transactions[].ai_description` | string | Verbose, multi-sentence description | unchanged |
| `transactions[].category` | string | Always one of the maintained category list's `name` values | unchanged |
| `transactions[].amount` | number | Always a positive magnitude | unchanged |
| `transactions[].transaction_type` | `"debit" \| "credit" \| "fee" \| "transfer"` | | unchanged |
| `transactions[].balance` | number or `null` | Running balance after this transaction, when stated in the source; `null` when not determinable | **new field** |
| `transactions[].duplicate_of` | string (UUID) or `null` | Existing `transactions` row id this entry likely duplicates | unchanged |
| `transactions[].extra_fields` | object, key present only when non-empty | Any other per-transaction data beyond the shape above | **was `[{key, value}]`; now a plain object** |
| `normalized_json.extra_fields` | object, present only when non-empty | Statement-level facts beyond the dedicated fields above | **was `[{key, value}]`; now a plain object** |
| `model_used` | string | The configured model name that produced the result | unchanged |

## Response — failure — unchanged

Same `401`/`404`/`422`/`502` behavior as spec 005's contract; no new status code, no partial-success
shape.

## What this endpoint explicitly does NOT do — unchanged, plus one addition

Same list as spec 005 (does not re-invoke document processing; does not write any backend-owned
table; does not create/update/link a `bank_accounts` row — `account_number` remains informational
output only, not an account-linking side effect performed by this service; does not perform
LLM-judged duplicate detection; does not expose a category-management API) — **plus**: does not
extend telemetry redaction to cover the new `account_number` field (tracked separately, see plan.md
Constitution Check / Clarifications — this service's Langfuse export of the underlying LLM call may
currently carry the unmasked value un-redacted).
