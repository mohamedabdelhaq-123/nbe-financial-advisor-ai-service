"""Splits OCR content into extraction portions (chunks).

Table entries are portioned primarily by estimated transaction-row count
(FR-007), derived from the configured output-token budget; non-`table` entries
pack liberally under a character-length fallback ceiling (renamed
`_MAX_PORTION_CHARS`) and are NOT counted against the row cap, since they don't
scale extraction output the way transaction rows do. The character ceiling also
remains the safety net for a single pathologically large row (FR-008): such a
row is never dropped, just emitted as an oversized-but-non-empty portion.

Uses a real HTML parser (BeautifulSoup), not regex, for table-row handling
(Constitution VIII).
"""

import json
import math

from bs4 import BeautifulSoup

from app.core.config import settings

# Fallback character ceiling — the safety net beneath the row-count primary
# driver (FR-008). Same value as the former `_MAX_CHUNK_CHARS`; renamed to
# reflect its demoted role.
_MAX_PORTION_CHARS = 1200

# Mirrors spec 005 §16's finding: a reasoning-model backend can spend a large,
# non-fixed share of its budget on hidden reasoning tokens before emitting the
# JSON, so only ~70% of the token budget is available for actual output rows.
_ROW_BUDGET_FACTOR = 0.7


def _row_cap(chunk_max_tokens: int, est_tokens_per_row: int) -> int:
    """Max transaction rows per portion (FR-007). Always >= 1 (FR-008)."""
    return max(1, math.floor(_ROW_BUDGET_FACTOR * chunk_max_tokens / est_tokens_per_row))


def _default_max_rows() -> int:
    return _row_cap(
        settings.chat_model.normalization_chunk_max_tokens,
        settings.chat_model.normalization_est_tokens_per_row,
    )


def _count_table_rows(entry: dict) -> int:
    if entry.get("type") != "table":
        return 0
    return len(BeautifulSoup(entry.get("table_body") or "", "html.parser").find_all("tr"))


def _split_table_entry(entry: dict, max_rows: int) -> list[dict]:
    """Split one table entry into portions of at most `max_rows` `<tr>` rows each.

    Non-`table_body` fields (e.g. `page_idx`, `table_caption`) are preserved
    verbatim on every portion. A table already within the row cap is returned
    unchanged (no portions).
    """
    rows = BeautifulSoup(entry.get("table_body") or "", "html.parser").find_all("tr")
    if len(rows) <= max_rows:
        return [entry]
    return [
        {
            **entry,
            "table_body": f"<table>{''.join(str(r) for r in rows[i : i + max_rows])}</table>",
        }
        for i in range(0, len(rows), max_rows)
    ]


def _split_into_chunks(
    content_list: list,
    markdown: str,
    max_chars: int = _MAX_PORTION_CHARS,
    max_rows: int | None = None,
) -> list[list[dict]]:
    """Split OCR content into extraction portions.

    `table` entries are pre-split into row-capped portions (FR-007); then all
    entries are packed greedily, never exceeding `max_rows` transaction rows or
    `max_chars` characters per portion (whichever binds first). Non-`table`
    entries contribute zero rows, so they never trigger the row cap. A single
    entry larger than both limits is still emitted as its own oversized portion
    rather than dropped (FR-008).
    """
    if max_rows is None:
        max_rows = _default_max_rows()

    if not content_list:
        return [[{"type": "text", "text": markdown}]] if markdown.strip() else []

    atomic_entries: list[dict] = []
    for entry in content_list:
        if entry.get("type") == "table":
            atomic_entries.extend(_split_table_entry(entry, max_rows))
        else:
            atomic_entries.append(entry)

    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_size = 0
    current_rows = 0
    for entry in atomic_entries:
        entry_size = len(json.dumps(entry))
        entry_rows = _count_table_rows(entry)
        would_exceed_rows = current_rows + entry_rows > max_rows
        would_exceed_chars = current_size + entry_size > max_chars
        if current and (would_exceed_rows or would_exceed_chars):
            chunks.append(current)
            current, current_size, current_rows = [], 0, 0
        current.append(entry)
        current_size += entry_size
        current_rows += entry_rows
    if current:
        chunks.append(current)

    return chunks
