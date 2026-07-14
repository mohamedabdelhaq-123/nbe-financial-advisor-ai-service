# Quickstart: Validating the Text Embedding Service

Validates the feature end-to-end once implemented, against `contracts/embeddings-api.md` and `spec.md`'s acceptance scenarios.

## Prerequisites

- Repo checked out on branch `007-embedding-service`, dependencies installed (`uv sync`).
- A `.env` (or exported env vars) with at minimum `AI_SERVICE_TOKEN` set and `USE_MOCK_LLM=1` — no real OpenAI credentials needed to validate the mock path.

## 1. Internal core service (US1)

```bash
uv run python -c "
import asyncio
from app.core.embedding import get_embedding_model

async def main():
    model = get_embedding_model()
    v1 = await model.aembed_documents(['low-fee savings account'])
    v2 = await model.aembed_documents(['low-fee savings account'])
    v3 = await model.aembed_documents(['a completely different sentence'])
    assert len(v1[0]) == 768
    assert v1 == v2, 'same text must yield identical vectors in mock mode (FR-004)'
    assert v1 != v3, 'different text must yield different vectors'
    print('OK: core service deterministic in mock mode, 768-dim')

asyncio.run(main())
"
```

Expected: prints `OK: core service deterministic in mock mode, 768-dim` — validates FR-001/002/004 and SC-005.

## 2. Existing `recommendations` feature stays unaffected

```bash
uv run pytest tests/features/recommendations -q
```

Expected: all existing tests pass unmodified — confirms `embed_texts()`'s call signature is unchanged (Structure Decision in `plan.md`).

## 3. HTTP endpoint (US2)

Start the app (`uv run uvicorn app.main:app --reload`), then:

```bash
# No token -> 401 (US2 acceptance scenario 3)
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/internal/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"input": "hello"}'

# Valid token, single input -> 200, one vector (US2 acceptance scenario 1)
curl -s -X POST http://localhost:8000/internal/embeddings \
  -H "Authorization: Bearer $AI_SERVICE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"input": "low-fee savings account"}' | python3 -m json.tool

# Valid token, batch input -> 200, one vector per input, same order (US2 acceptance scenario 2)
curl -s -X POST http://localhost:8000/internal/embeddings \
  -H "Authorization: Bearer $AI_SERVICE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"input": ["first text", "second text"]}' | python3 -m json.tool

# Empty input -> 422 (FR-008 / SC-004)
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/internal/embeddings \
  -H "Authorization: Bearer $AI_SERVICE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"input": []}'
```

Expected: `401`, then a `200` response shaped per `contracts/embeddings-api.md` with `data[0].embedding` length `768`, then a `200` with two ordered `data` entries, then `422`.

## 4. Automated test suite

```bash
uv run pytest tests/core/test_embedding.py tests/features/embed -q
uv run ruff check app/core/embedding.py app/features/embed
uv run mypy app/core/embedding.py app/features/embed
```

Expected: all green — satisfies Constitution Principle I (mock-first, deterministic tests) and the CI quality gates (Principle VIII compliance is a PR-review judgment call, not an automated gate).
