# Research: Mock MinerU Client for Offline Ingestion

All Technical Context items were already resolvable from the existing codebase and the
spec's Clarifications session — no NEEDS CLARIFICATION markers remain. This document
records the design decisions and their rationale.

## 1. Swappable-client pattern to mirror

**Decision**: Implement `MockMineruClient` as a second, plain implementation of the
existing `MineruClient` Protocol in `app/features/ingestion/mineru_client.py`, selected
by `get_mineru_client()` branching once on `settings.use_mock_mineru` — exactly mirroring
`MockNormalizerClient` (`app/features/ingestion/normalizer/mock.py`) and its factory
(`get_normalizer_client()` in `app/features/ingestion/normalizer/__init__.py:47-49`,
branching on `settings.use_mock_llm`).

**Rationale**: Constitution Principle VIII (Library-First, Minimal Implementation)
explicitly requires reusing an existing pattern that already fits — "a swappable-client
shape" — rather than inventing a parallel one. This exact seam (`Protocol` +
factory-level branch on a settings flag) is already shipped and battle-tested for the
normalizer. `research.md §8` from the original document-processor feature
(`specs/004-document-processor/research.md`) already specified this exact seam and
explicitly deferred only the mock's existence, not its shape — this plan fulfills that
deferred item as designed.

**Alternatives considered**:
- A test-only dependency override (e.g. FastAPI `Depends()` override or a pytest fixture
  monkeypatching `get_mineru_client` per test) — rejected because it doesn't fix the
  actual defect: `USE_MOCK_MINERU=1` must work for a real running process (local dev,
  offline CI container), not just inside the test suite, which already has its own
  `_FakeMineruClient` test doubles (`tests/features/ingestion/test_service.py:124-138`)
  that remain unaffected and unnecessary to change.
- Loading fixture content from a file on disk — rejected as unnecessary file I/O and
  packaging overhead for a fixed literal that never varies; conflicts with the
  minimal-implementation principle.

## 2. `content_list` table entry shape

**Decision**: The mock's table-like `content_list` entry uses the `table_body` key
(an HTML `<table>...</table>` string), not a `rows` array.

**Rationale**: `app/features/ingestion/normalizer/chunking.py::_split_table_entry`
(line 26) reads `entry.get("table_body")`, parsed via BeautifulSoup — this is the only
key the real (non-mocked) normalizer pipeline's chunking logic understands. Spec User
Story 3 requires the offline parsing output to remain plausible when mock document
parsing is combined with the real (non-mocked) LLM normalizer, so the mock must use the
key that code path actually reads. A `rows`-array shape appears only in ad hoc test
fixtures (`tests/features/ingestion/test_mineru_client.py`) and is never read by
production code.

**Alternatives considered**: A `rows`-array entry — rejected; it would satisfy
"non-empty" checks but silently fail User Story 3's downstream-plausibility requirement,
since `_split_table_entry` would treat it as an opaque atomic entry rather than
recognizable tabular content.

## 3. Content richness, images, and failure simulation

**Decision** (locked in by spec.md Clarifications, session 2026-07-15):
- `content_list` contains exactly two entries: one `type: "text"` entry and one
  `type: "table"` entry (single row), both describing the same one mock transaction.
- `images` is always `{}` (empty).
- No failure-simulation or input-inspection capability — `parse_document()` always
  succeeds and always returns the same fixed output regardless of `file_bytes`/`filename`.

**Rationale**: Table-splitting/multi-row chunking behavior already has dedicated test
coverage in `chunking.py`'s own test suite — duplicating richer multi-row content here
would be scope creep beyond "enable offline running" (constitution VIII minimalism).
Error-path testing already has its own seam (`_FakeMineruClient` raising exceptions in
`test_service.py`), so adding configurability for failures to this mock would duplicate
an already-solved problem. Heuristic/best-effort inspection of the actual submitted
bytes was explicitly rejected in the Clarifications session because it would reintroduce
non-determinism, contradicting FR-004.

**Alternatives considered**: Multi-row/richer content; a constructor-configurable
failure mode; best-effort real parsing of input bytes. All explicitly rejected — see
spec.md Clarifications for the recorded reasoning.

## 4. Configuration surface

**Decision**: No new settings. Reuse `settings.use_mock_mineru`
(`app/core/config.py:85`), whose startup validation (`app/core/config.py:151-155`,
requiring `MINERU_API_URL` unless the flag is true) already exists and is correct.

**Rationale**: The only defect is that `get_mineru_client()` never reads the flag. FR-005
and FR-007 in the spec lock in that no configuration changes are needed or permitted.

**Alternatives considered**: None — a second flag was never a viable option since one
already exists for exactly this purpose.

## 5. No `/contracts/` artifact

**Decision**: This feature does not produce a `contracts/` directory.

**Rationale**: `MockMineruClient` is an internal `Protocol` implementation swapped in
behind an existing internal interface (`MineruClient.parse_document`); it introduces no
new externally-exposed HTTP endpoint, request/response schema, or public API. The
existing protocol signature (`async def parse_document(file_bytes: bytes, filename: str)
-> ParsedDocument`) is unchanged.
