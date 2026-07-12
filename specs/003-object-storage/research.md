# Phase 0 Research: Object Storage Infrastructure

All technical unknowns for this feature were resolved through direct
investigation and discussion before this plan was written (see the
Technical Context constraints in `plan.md`); no `NEEDS CLARIFICATION`
markers remain. This document consolidates those decisions in the
standard Decision / Rationale / Alternatives format.

## 1. S3-compatible client library

**Decision**: `aioboto3` (backed by `aiobotocore`/`botocore`).

**Rationale**: `aioboto3` is a mature, actively-maintained, well-documented
async S3 client with a straightforward session/client lifecycle
(`aioboto3.Session()` created once, cheap and I/O-free; a fresh client
opened per operation via `async with session.client("s3", ...) as s3:`).
Every method call is a genuine coroutine — no thread-pool wrapping needed
to keep FastAPI's event loop unblocked.

**Alternatives considered**:
- **`fsspec` + `s3fs` (sync mode, wrapped in `asyncio.to_thread`)** —
  works, but adds a layer of indirection: s3fs's default sync API blocks
  on a background event loop internally, so wrapping it in
  `asyncio.to_thread` moves an already-indirect blocking wait onto a
  worker thread for no net benefit over calling an async-native client
  directly.
- **`fsspec` + `s3fs` with `asynchronous=True`** — gives native coroutine
  methods (`_pipe_file`, `_cat_file`, ...), but this mode is thinly
  documented upstream; even experienced users report uncertainty about
  session-lifecycle and event-loop-binding rules (fsspec/s3fs#503, #907).
  This was seriously considered and prototyped in an earlier draft of this
  plan, but dropped once local-filesystem support (see §2) was dropped —
  fsspec's main value (one interface spanning two backends with different
  sync/async shapes) no longer applied, so there was no remaining reason
  to accept its documented rough edges over aioboto3's simpler, better-
  trodden lifecycle.
- **Raw `boto3` wrapped in `asyncio.to_thread`** — works but reintroduces
  the same "sync client wrapped for async" indirection as the s3fs-sync
  option, with no fsspec convenience gained in exchange.

## 2. Backend scope: S3-only vs. dual local-filesystem + S3

**Decision**: S3-compatible only. No local-filesystem storage backend.

**Rationale**: This service's deployment target already has SeaweedFS
running as shared infrastructure; there is no requirement to support a
disk-backed mode. Dropping it removes an entire axis of design complexity
(a `storage_backend` config switch, two code paths with different
sync/async shapes, and the class-based abstraction that existed solely to
give both backends one call signature).

**Alternatives considered**: A dual local/S3 backend (selected via a
`storage_backend: Literal["local", "s3"]` setting) was the original design
direction, motivated by wanting a zero-network local dev experience. Ruled
out once it became clear the deployment always has a real S3-compatible
target available and per-environment config already covers "point at a
different bucket/endpoint" without needing an actual local-disk code path.

## 3. Access pattern: plain callable vs. FastAPI `Depends`

**Decision**: `get_storage_backend()` is a plain, directly-callable
function — not registered as a FastAPI dependency.

**Rationale**: Checked how this codebase actually draws the line between
the two shapes before deciding, rather than assuming:
`app/core/db.py`'s `get_own_session()` is `Depends`-based because a DB
session carries real per-request transaction lifecycle. But
`app/features/analytics/jobs/monthly_summary.py` shows the convention for
shared infra consumed *outside* router code: `embed_fn`/`session_gen` are
passed in or imported as plain callables. `Depends` only resolves inside
FastAPI's request-handling cycle, and FR-010 requires this capability work
from background jobs and agent/graph nodes with no active HTTP request —
a `Depends`-only design would block those call sites entirely.

**Alternatives considered**: A `Depends(get_storage_backend)` dependency
mirroring `get_own_session()` was considered, since aioboto3 clients are
themselves opened/closed per use (a shape that maps naturally onto
`Depends`'s yield-based lifecycle). Rejected because it would only be
usable from router-handler signatures, violating FR-010.

## 4. Wrapper API shape

**Decision**: No `write_bytes`/`read_bytes`-style wrapper functions.
Callers use boto3's own `put_object`/`get_object`/`head_object`/
`delete_object`/`list_objects_v2` directly against the client
`get_storage_backend()` hands them. The only shared code is
`validate_storage_key()`, a small traversal guard.

**Rationale**: With only one backend (see §2), a wrapper's only remaining
job would be renaming boto3's own well-known method names for no
behavioral difference — a translation layer earning nothing. Callers
already need to know they're talking to S3-shaped storage (they supply
`Bucket=settings.storage_s3_bucket`), so exposing the standard boto3 verbs
directly is the leaner choice and matches this project's general
preference against introducing abstraction that isn't earning its keep.

**Alternatives considered**: An earlier draft defined a `Protocol` plus
`LocalStorageBackend`/`S3StorageBackend` classes so both backends shared
one call signature — dropped alongside the local backend itself (§2),
since fsspec/aioboto3 already does the actual protocol work; the class
layer was scaffolding purely for cross-backend uniformity that no longer
has a second backend to unify with.

## 5. Local dev/test target: assume already-running SeaweedFS vs. bundled container

**Decision**: Assume SeaweedFS is already running as shared infrastructure
this feature does not provision. No `docker-compose.yml` service, no
bundled S3 identity config file. This feature only builds the config
surface (`storage_s3_endpoint_url`/`storage_s3_bucket`/credentials) to
point at wherever it runs.

**Rationale**: Explicit user direction — SeaweedFS is operated as shared
infra outside this feature's scope. Bundling a container the feature
doesn't otherwise need would be scope creep.

**Alternatives considered**: Adding a `seaweedfs` service to
`docker-compose.yml` (with a dev-only S3 identity config file) was
prototyped in an earlier draft, as was a Testcontainers-based SeaweedFS
fixture for integration tests. Both dropped for the reason above.

## 6. Key-traversal safety

**Decision**: `validate_storage_key(key)` rejects any key that isn't
already its own `posixpath.normpath` result, or that starts with `/` or
resolves to `..` — called before any operation touches the network.

**Rationale**: Directly satisfies FR-007/SC-004 (reject traversal-capable
keys before any network call). Centralizing this in one function means
every feature that stores blobs gets the same guard for free rather than
re-implementing it per call site.

**Alternatives considered**: Relying solely on S3's own key semantics
(which do not resolve `..` as a path-traversal operator the way a
filesystem does) was considered sufficient by some early framings — but
was rejected because it doesn't defend future call sites that might
concatenate keys before a local-cache layer or logging path, and it costs
nothing to check centrally regardless.

## 7. Testing strategy for the S3-compatible round-trip

**Decision**: Follow the same optional-when-configured pattern already
established for `backend_db_host` — a fixture reads
`STORAGE_S3_ENDPOINT_URL`/`STORAGE_S3_BUCKET`/`STORAGE_S3_ACCESS_KEY`/
`STORAGE_S3_SECRET_KEY` from the environment and `pytest.skip(...)` if
unset; the integration test runs a real round-trip only when a developer
or CI has these pointed at a real reachable SeaweedFS instance.

**Rationale**: Matches Constitution Principle I (CI stays green and
offline by default; live-infra tests are opt-in, never required) and
reuses a pattern already proven in this codebase rather than introducing a
second, differently-shaped mechanism.

**Alternatives considered**: A Testcontainers-based SeaweedFS fixture
(spinning up a real container per test session) was prototyped in an
earlier draft — dropped alongside §5's decision not to have this feature
own any SeaweedFS container lifecycle, dev or test.
