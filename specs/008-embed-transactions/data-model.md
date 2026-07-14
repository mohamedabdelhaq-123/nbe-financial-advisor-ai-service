# Data Model: Transaction Embedding by ID

**Feature**: [spec.md](./spec.md) | **Date**: 2026-07-14

No new tables are introduced. This feature reads and narrowly writes an existing
backend-owned table (`transactions`, via the already-generated `Transaction` model
in `app.backend_db.models`) and writes to the existing service-owned audit table
(`ai_audit_log`, via `AiAuditLog` / `record_audit`). The request/response shapes
below are transient DTOs, not persisted entities.

## Transaction (existing, backend-owned — read + narrow write)

Source: `app.backend_db.models.Transaction` (generated mirror of the backend's
`transactions` table). This feature does not add or change any column.

| Field | Used how |
|---|---|
| `id` (UUID, PK) | Read — the identifier this feature's request accepts |
| `merchant_normalized` (str, nullable) | Read — preferred merchant text for the embedding summary |
| `merchant_raw` (str, nullable) | Read — fallback merchant text if `merchant_normalized` is empty |
| `category` (str, nullable) | Read — included in the embedding summary |
| `amount` (Decimal) | Read — included in the embedding summary |
| `currency` (str) | Read — included in the embedding summary |
| `transaction_date` (date) | Read — included in the embedding summary |
| `embedding` (`vector(1536)`, nullable) | **Write** — the only column this feature ever writes; overwritten on every successful call for that transaction (FR-005, FR-007) |

**Validation rule**: every ID in a request must resolve to an existing `Transaction`
row; if any does not, no row's `embedding` is written for that request (FR-006).

**Constraint honored, not introduced**: the write is possible only because of the
existing narrow `GRANT UPDATE (embedding) ON transactions TO ai_readonly` plus a
per-transaction `SET TRANSACTION READ WRITE` override (see [research.md](./research.md)).

## TransactionEmbedRequest (new, transient — request DTO)

| Field | Type | Rule |
|---|---|---|
| `transaction_ids` | `list[UUID]` | 1–500 entries (FR-004, FR-013); duplicates collapse to one embedding operation per unique ID (Assumptions) |

## TransactionEmbedResult (new, transient — per-ID outcome, response DTO)

| Field | Type | Rule |
|---|---|---|
| `transaction_id` | `UUID` | Echoes a requested ID |
| `status` | `Literal["embedded"]` | Present only on a fully successful request (FR-009); an all-or-nothing failure returns no partial results (see contract) |

## AiAuditLog (existing, own DB — one row per successful request)

Source: `app.features.audit.models.AiAuditLog`, written via
`app.core.audit.record_audit` (FR-012). No schema change.

| Field | Value for this feature |
|---|---|
| `action` | `"transactions.embed"` |
| `detail_json` | `{"transaction_ids": [<all requested UUIDs as strings>]}` |
| `user_id` | `None` (no single end-user is attributable — the backend, not a user, is the caller) |
