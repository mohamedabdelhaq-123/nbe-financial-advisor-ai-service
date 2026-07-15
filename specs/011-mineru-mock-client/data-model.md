# Data Model: Mock MinerU Client for Offline Ingestion

This feature introduces no database tables, migrations, or persisted entities. The one
relevant entity is the existing in-memory value object already defined by the
`MineruClient` Protocol's return type — reused as-is, not modified.

## `ParsedDocument` (existing dataclass, `app/features/ingestion/mineru_client.py`)

| Field | Type | Description |
|---|---|---|
| `markdown` | `str` | Extracted document text, as Markdown. |
| `content_list` | `list` | Structured content fragments extracted from the document. |
| `images` | `dict[str, bytes]` | Extracted image filename → raw bytes (defaults to `{}`). |

No fields, types, or defaults change. `MockMineruClient.parse_document()` returns an
instance of this same dataclass — this is what keeps it a drop-in swap for
`HttpMineruClient` behind the `MineruClient` Protocol.

## Fixed content `MockMineruClient` returns

Locked in by spec.md's Clarifications (session 2026-07-15). Always identical, regardless
of the `file_bytes`/`filename` arguments:

- **`markdown`**: non-empty, statement-shaped text (a heading plus a one-row table
  rendered as Markdown), describing one fixed mock transaction (date, merchant-like
  text, amount).
- **`content_list`**: exactly two entries, both describing that same one mock
  transaction so the output stays internally consistent:
  1. `{"type": "text", "text": <statement-like text>, "page_idx": 0}`
  2. `{"type": "table", "table_body": <single-row HTML `<table>...</table>` string>}` —
     uses the `table_body` key specifically because
     `app/features/ingestion/normalizer/chunking.py::_split_table_entry` reads exactly
     that key when the real (non-mocked) normalizer processes this output.
- **`images`**: always `{}`.

## Relationships / lifecycle

None. `ParsedDocument` is a pure, immutable-in-practice value object constructed and
returned synchronously per call (via an `async def` method for protocol compliance) with
no side effects, no persistence of its own, and no state transitions. Downstream
persistence of its fields (to object storage) is handled by the existing, unmodified
`app/features/ingestion/service/process.py`.
