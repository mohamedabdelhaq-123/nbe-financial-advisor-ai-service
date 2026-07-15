# Quickstart: Validate the Mock MinerU Client

Prerequisites: repo checked out, dependencies installed (`uv sync`), and the usual
required `.env` values set (`AI_SERVICE_TOKEN`, storage S3 vars, etc. — unrelated to
this feature and already required today).

## 1. Unit-level validation (fastest, no server, no DB)

```bash
uv run pytest tests/features/ingestion/test_mineru_client.py -v
```

Expected, once implemented:
- `get_mineru_client()` returns a `MockMineruClient` instance when
  `settings.use_mock_mineru` is `True`, and an `HttpMineruClient` instance when `False`
  (mirrors `test_get_normalizer_client_returns_mock_when_use_mock_llm` /
  `..._returns_langgraph_when_not_mock` in `tests/features/ingestion/test_normalizer.py:357-372`).
- `MockMineruClient().parse_document(b"anything", "anything.pdf")` returns a
  `ParsedDocument` with: non-empty `markdown`; `content_list` containing exactly two
  entries (one `type: "text"`, one `type: "table"` with a `table_body` key); and
  `images == {}` — identical across repeated calls and different input bytes/filenames
  (per data-model.md).

## 2. Service-level validation (proves `USE_MOCK_MINERU=1` actually takes effect)

The existing `tests/features/ingestion/test_service.py` suite validates
`process_statement()` by monkeypatching `get_mineru_client` directly with a
`_FakeMineruClient` — that path is unaffected by this feature. To confirm the *real*
defect this feature fixes is closed, run (or add, if not already covered) a scenario
that sets `settings.use_mock_mineru = True` via monkeypatch **without** overriding
`get_mineru_client`, and confirms `process_statement()` completes successfully with no
outbound HTTP call attempted — proving the factory-level wiring, not just an injected
test double, is what makes offline mode work.

## 3. Manual/local end-to-end check

```bash
# In .env:
USE_MOCK_MINERU=1
# MINERU_API_URL left empty/unreachable — startup must NOT raise
# (per app/core/config.py:151-155, unchanged by this feature)
```

Start the service normally. `POST /internal/ingestion/process` (see
`app/features/ingestion/router.py`) requires a pre-existing statement row and a valid
`AI_SERVICE_TOKEN` bearer token — provisioning one from scratch is outside this
feature's scope, so exercise this via the project's existing integration-test fixtures
(Testcontainers-backed, see `tests/features/ingestion/test_service.py`) rather than a
hand-rolled `curl` call. Expected outcome: the request succeeds with no MinerU
connectivity error, and the persisted `markdown`/`content_list` in storage match the
mock's fixed output described in data-model.md.

## 4. Regression check (real mode untouched)

```bash
uv run pytest tests/features/ingestion/ -v
```

All existing tests — including `HttpMineruClient`/ZIP-extraction tests in
`test_mineru_client.py` and the `_FakeMineruClient`-injected tests in
`test_service.py` — continue to pass unmodified, confirming real-mode behavior is
unaffected.

## 5. Full gate

```bash
uv run pytest
uv run ruff check .
uv run black --check .
uv run mypy .
```

All green, per the constitution's CI merge-gate requirements.
