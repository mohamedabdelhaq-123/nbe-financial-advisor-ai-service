# Contract: `POST /internal/ingestion/normalize`

Internal endpoint, called only by the Django backend. Requires the same shared-secret Bearer token
as every other internal route (`require_token`).

## Request

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

| Field | Type | Required | Notes |
|---|---|---|---|
| `ocr_result_id` | string (UUID) | yes | Must reference an existing `statement_ocr_results` row (Part 1's output) |

## Response — success (200)

```json
{
  "normalized_json": {
    "bank_name": "National Bank of Egypt",
    "account_hint": "****1234",
    "transactions": [
      {
        "transaction_date": "2026-05-01",
        "merchant_raw": "Carrefour #abc123",
        "ai_description": "A grocery purchase at a Carrefour supermarket, likely a routine household shopping trip based on the amount and merchant category.",
        "category": "groceries",
        "amount": 1234.56,
        "transaction_type": "debit",
        "duplicate_of": null,
        "extra_fields": [
          {"key": "reference_number", "value": "421IPNM243040054"},
          {"key": "value_date", "value": "2026-05-01"}
        ]
      }
    ],
    "extra_fields": [
      {"key": "account_number", "value": "4213010248203200016"},
      {"key": "opening_balance", "value": "24.57"}
    ]
  },
  "model_used": "gpt-4o-mini"
}
```

| Field | Type | Notes |
|---|---|---|
| `normalized_json` | object | Also written verbatim to `{bucket}/{statement_id}/normalized.json` (same bucket/prefix Part 1 uses for that statement, resolved via the OCR result's `statement_id`). |
| `normalized_json.bank_name` | string or `null` | Best-effort; `null` when not determinable from source content. |
| `normalized_json.account_hint` | string or `null` | Best-effort masked account reference; `null` when not determinable. |
| `normalized_json.transactions` | array | Zero or more entries; an empty array is a valid, successful result (FR-015), not an error. |
| `transactions[].transaction_date` | string (`YYYY-MM-DD`) | Entry is omitted entirely rather than included if this can't be confidently determined. |
| `transactions[].merchant_raw` | string | As extracted. |
| `transactions[].ai_description` | string | Verbose, multi-sentence LLM-generated description of the transaction — deliberately more detailed than `merchant_raw`, never just a copy of it (research.md §15). |
| `transactions[].category` | string | Always one of the maintained category list's `name` values (never free text) — see `data-model.md`. |
| `transactions[].amount` | number | Always a positive magnitude — direction is `transaction_type`, never the sign of `amount`. |
| `transactions[].transaction_type` | `"debit" \| "credit" \| "fee" \| "transfer"` | |
| `transactions[].duplicate_of` | string (UUID) or `null` | Existing `transactions` row id this entry likely duplicates, or `null` if none found (research.md §4). |
| `transactions[].extra_fields` | `[{key, value}]`, key present on the object only when the list is non-empty | Any other per-transaction data visible in the source beyond the minimum shape above (e.g. reference number, value date, running balance) — the documented shape is a *minimum*, not an exhaustive list (research.md §14). |
| `normalized_json.extra_fields` | `[{key, value}]`, present only when non-empty | Statement-level facts beyond `bank_name`/`account_hint` (e.g. account number, currency, statement period, opening/closing balance). |
| `model_used` | string | The configured model name that produced the result (`settings.model_name`), e.g. `"gpt-4o-mini"`. |

## Response — failure

| Status | Condition | Body shape |
|---|---|---|
| `422` | `ocr_result_id` is not a valid UUID | `{"detail": [...]}` (standard FastAPI/Pydantic validation error — the request schema types `ocr_result_id` as a UUID) |
| `401` | Missing/invalid Bearer token | `{"detail": "Invalid or missing token"}` (existing `require_token` behavior) |
| `404` | `ocr_result_id` does not match any known OCR result | `{"detail": "ocr result not found"}` |
| `502` | The OCR artifacts (`markdown.md`/`content_list.json`) could not be retrieved from storage, **or** the LLM call failed/returned an unparseable result | `{"detail": "..."}` — message distinguishes which side failed |

No other status codes are part of this contract. There is no partial-success shape — a request
either returns the full `normalized_json`/`model_used` body or an error; nothing is persisted
(neither the storage object nor the audit row) for a request that ultimately fails.

## What this endpoint explicitly does NOT do

- Does not re-invoke MinerU / document processing — it only reads Part 1's already-persisted
  artifacts.
- Does not write to any backend-owned table (`statement_normalized` or otherwise) — the backend
  persists that itself using this response, matching that table's `normalized_json`/`model_used`
  columns.
- Does not create, update, or link a `bank_accounts` row — `account_hint` is informational output
  only, not an account-linking side effect.
- Does not perform LLM-judged duplicate detection — `duplicate_of` is computed deterministically
  (research.md §4), not by asking the model to compare against existing transactions.
- Does not expose an API to add/edit categories — the category list is seeded via migration;
  managing it further is a later, separate capability.
