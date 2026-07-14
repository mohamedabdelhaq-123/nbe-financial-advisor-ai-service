# Research: Transaction Embedding by ID

**Feature**: [spec.md](./spec.md) | **Date**: 2026-07-14

All unknowns from the spec are domain decisions already resolved during
`/speckit-clarify` (embedding text composition, batch cap/sync model, all-or-nothing
failure handling, audit granularity, no-redaction). What remains here is the
technical grounding needed to implement those decisions correctly against the
existing codebase and infrastructure.

## Decision: Backend DB write path requires an explicit per-transaction READ WRITE override

**Finding**: `ai_readonly` (the role this service's backend DB connection uses) was
provisioned with `ALTER ROLE ai_readonly SET default_transaction_read_only = on`
(Django migration `core/migrations/0009_grant_ai_readonly_role.py`), on top of the
narrow `GRANT UPDATE (embedding) ON transactions` and full CRUD on
`monthly_summaries`. `default_transaction_read_only = on` is a Postgres
transaction-level setting, independent of GRANTs: every transaction opened by this
role starts in read-only mode and rejects INSERT/UPDATE/DELETE even against tables
it has been explicitly granted write access to, unless that specific transaction
overrides the default.

**Decision**: The transaction-embedding write path MUST issue `SET TRANSACTION READ
WRITE` as the first statement inside the backend DB transaction used to persist
embeddings, before any `UPDATE`. All other backend DB access in this service (every
existing SELECT-only usage via `get_backend_session()`) is unaffected and continues
to run under the read-only default — this override is scoped narrowly to the one
write transaction this feature opens.

**Rationale**: Without the override, every `UPDATE transactions SET embedding = ...`
issued by this service fails with a Postgres read-only-transaction error regardless
of the column-level GRANT already in place. This is a deliberate defense-in-depth
choice by the role's provisioner (comment in the migration: "Narrow, explicit write
exceptions on top of the otherwise SELECT-only role") — the GRANT makes the write
*possible*, the per-transaction override makes it *actually happen*, and every other
code path in the service that never issues the override stays hard-blocked from
writing even if a future bug tried to.

**Alternatives considered**:
- A second Postgres role without `default_transaction_read_only` dedicated to
  writes — rejected: adds a second backend credential/connection pool to manage for
  a need the existing role, combined with one SQL statement, already covers.
- Relying on the GRANT alone — rejected: verified against the migration that this
  does not work; Postgres enforces the transaction-mode restriction before GRANT
  checks are consulted for write statements.

## Decision: Constitution Principle IV — enumerated, explicitly authorized exception

**Finding**: Constitution Principle IV (pre-v2.2.0) stated the backend DB "is
READ-ONLY... access MUST go through a dedicated read-only database role
(DB-enforced)... the application MUST define no write paths against it," and no
code in this repository wrote to a `BackendBase`-bound model at the time (grep
confirmed every existing `session.add`/write in the codebase targeted `OwnBase`
models).

**Decision**: Rather than treat this as a per-feature deviation to justify in
Complexity Tracking, the constitution itself was amended (v2.1.0 → v2.2.0) to
formally enumerate this as an authorized exception: Principle IV now states the
backend DB is read-only *by default*, with write paths permitted only where both a
narrowly-scoped DB-level GRANT and explicit human authorization exist — and lists
`transactions.embedding` (UPDATE only) and `monthly_summaries` (full CRUD) as the
two currently-authorized exceptions, matching the `ai_readonly` role's grants
exactly (migration `core/migrations/0009_grant_ai_readonly_role.py`: "the AI
service backfills computed embeddings and owns monthly_summaries end to end").
This feature's write surface is scoped to match that enumeration exactly — only
the `embedding` column of `transactions` is ever written, via a single, isolated
write path, with every other `BackendBase` access in the service remaining
strictly read-only.

**Rationale**: Recording the exception in the constitution (rather than only in
this feature's Complexity Tracking) keeps the written principle from contradicting
already-provisioned, sanctioned DB access, and gives every future feature a
durable, enumerated answer to "is this write allowed" instead of re-litigating the
question per PR. The amendment explicitly preserves the read-only default and
requires the same two-part authorization for any future exception, so this does
not loosen the boundary generally — see the constitution's Sync Impact Report
(v2.1.0 → v2.2.0).

**Alternatives considered**:
- Have Django perform the write instead, with this service only returning the
  vector — rejected: this is exactly the round-trip the feature (and the DB grant)
  exists to eliminate; it also does not match the user's explicit request or the
  narrow grant already provisioned for this service to write directly.
- Justify the write as a per-feature Complexity Tracking deviation without
  amending the constitution — rejected (superseded): the requester explicitly
  asked for the constitution to be updated so the exception is recorded formally
  and future features have an enumerated reference rather than a one-off
  justification.

## Decision: Feature slice placement

**Finding**: The existing `app/features/embed` slice owns the generic,
OpenAI-shaped `/internal/embeddings` endpoint (arbitrary caller-supplied text →
vectors, no persistence). `app/features/analytics` owns deterministic
transaction-aggregation jobs (monthly summary, anomaly detection) that read
`Transaction` rows but return computed results to the backend rather than writing
anything back. Neither is a fit for a transaction-specific, ID-driven, persisting
write operation.

**Decision**: New feature slice `app/features/transactions/` (router, schemas,
service — no models module needed, since it introduces no new own-DB table),
following Constitution Principle V. It reuses `app/features/embed/service.py:
embed_texts` (the shared embedding entry point, per FR-011) and
`app/core/audit.py: record_audit` (per FR-012) rather than reimplementing either.

**Rationale**: Keeps the vertical-slice boundary aligned with the domain concept
(transactions) this feature actually mutates, and matches Principle V's
self-contained-slice requirement without overloading `embed` (generic text→vector)
or `analytics` (read-only computed aggregates) with a responsibility neither owns.

**Alternatives considered**:
- Add to `app/features/analytics` — rejected: analytics is a read-only computation
  slice by design (Constitution VI: "Dashboard analytics MUST be produced by
  background pipeline jobs"); mixing in a direct-write endpoint blurs that
  boundary.
- Add to `app/features/embed` — rejected: that slice's contract is deliberately
  OpenAI-shaped and generic; transaction-specific text construction and backend
  writes don't belong behind that same generic surface.

## Decision: Embedding text construction and dimension

**Finding**: `app.backend_db.models.TRANSACTION_EMBEDDING_DIM` already derives the
fixed vector size (1536) directly from the `transactions.embedding` column's
`pgvector` type, mirroring the existing `MONTHLY_SUMMARY_EMBEDDING_DIM` pattern used
by `compute_monthly_summary`.

**Decision**: Build one line per transaction from its already-read-only-accessible
fields — merchant (prefer `merchant_normalized`, fall back to `merchant_raw`),
`category`, `amount`, `currency`, `transaction_date` — and pass the batch of lines
to `embed_texts(texts, dimensions=TRANSACTION_EMBEDDING_DIM)` in one call, mirroring
`compute_monthly_summary`'s existing `embed_fn(..., dimensions=...)` usage.

**Rationale**: Reuses the shared embedding entry point and dimension-derivation
pattern already established for `monthly_summaries`, satisfying FR-011 (centrally
managed configuration) and FR-003 (no redaction, structured summary) with no new
provider-facing code.

**Alternatives considered**: none beyond the three already evaluated and decided in
`/speckit-clarify`.

## Decision: Atomicity implementation

**Finding**: FR-006 and FR-010 both require all-or-nothing behavior: any invalid
requested ID, or any embedding-provider failure mid-batch, must leave zero
transactions written.

**Decision**: Open a single backend DB session/transaction for the whole request.
First, `SELECT` all requested transaction IDs in one query; if any are missing,
roll back (nothing was written yet) and return the invalid IDs without calling the
embedding provider at all. Otherwise, call `embed_texts` once for the full batch,
then issue one `UPDATE` per transaction (or a single bulk `UPDATE ... FROM (VALUES
...)`) inside the same transaction, and commit only after every row is updated. Any
exception before the final commit leaves the transaction uncommitted, so Postgres
discards all of it. The one audit log entry (own DB, separate connection) is only
written after the backend transaction commits successfully.

**Rationale**: This maps FR-006/FR-010's business requirement directly onto
Postgres's native transaction atomicity instead of hand-rolled compensating logic,
per Constitution Principle VIII (prefer the platform primitive over a hand-rolled
implementation).

**Alternatives considered**:
- Per-row commits with manual rollback/undo of already-written rows on later
  failure — rejected: reimplements what a single DB transaction already guarantees,
  and is not truly atomic under crash/network failure between steps.
