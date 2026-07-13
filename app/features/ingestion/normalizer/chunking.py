"""Splits OCR content into prompt-sized pieces.

Uses a real HTML parser (BeautifulSoup), not regex, for the one case that
needs it: splitting an oversized table at row boundaries (Constitution VIII).
"""

import json

from bs4 import BeautifulSoup

# Sized for OUTPUT, not input: per-transaction `extra_fields` roughly triples
# response verbosity, so a chunk sized only for input prompt length can still
# produce a completion that gets cut off mid-JSON. Confirmed against a real
# statement/model — 3000 chars of input per chunk produced ~12-row chunks
# whose completions exceeded even a generous max_tokens. Also confirmed:
# raising max_tokens to compensate backfires on a low-tier account — the
# provider's admission control counts `prompt_tokens + max_tokens` against
# the per-minute budget before generation even starts, so a higher ceiling
# makes a request MORE likely to be rejected, not less. Use
# `normalization_max_parallel_chunks` (default 1, opt-in) to trade latency
# for throughput instead of growing either of these.
_MAX_CHUNK_CHARS = 1200


def _split_table_entry(entry: dict, max_chars: int) -> list[dict]:
    rows = BeautifulSoup(entry.get("table_body") or "", "html.parser").find_all("tr")
    if not rows:
        return [entry]

    batches: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for row in rows:
        row_html = str(row)
        if current and current_size + len(row_html) > max_chars:
            batches.append(current)
            current, current_size = [], 0
        current.append(row_html)
        current_size += len(row_html)
    if current:
        batches.append(current)

    return [{**entry, "table_body": f"<table>{''.join(batch)}</table>"} for batch in batches]


def _split_into_chunks(
    content_list: list, markdown: str, max_chars: int = _MAX_CHUNK_CHARS
) -> list[list[dict]]:
    if not content_list:
        return [[{"type": "text", "text": markdown}]] if markdown.strip() else []

    atomic_entries: list[dict] = []
    for entry in content_list:
        if entry.get("type") == "table" and len(entry.get("table_body") or "") > max_chars:
            atomic_entries.extend(_split_table_entry(entry, max_chars))
        else:
            atomic_entries.append(entry)

    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    current_size = 0
    for entry in atomic_entries:
        entry_size = len(json.dumps(entry))
        if current_chunk and current_size + entry_size > max_chars:
            chunks.append(current_chunk)
            current_chunk, current_size = [], 0
        current_chunk.append(entry)
        current_size += entry_size
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _build_prompt(chunk: list[dict], known_categories: list[str] | None) -> str:
    category_hint = (
        f"Choose each transaction's category from exactly this list (no other values): "
        f"{known_categories}.\n"
        if known_categories
        else ""
    )
    return (
        "Extract structured transaction data from this fragment of a bank statement's "
        "OCR output. This may be only part of the full statement — extract only what's "
        "present here.\n\n"
        f"Content:\n{json.dumps(chunk)}\n\n"
        f"{category_hint}"
        "transaction_date must be converted to YYYY-MM-DD even if the source uses a "
        "different format (e.g. '30-October-2024' becomes '2024-10-30').\n"
        "Omit any transaction whose date or amount you cannot confidently determine.\n"
        "ai_description must be a verbose, multi-sentence natural-language description of "
        "each transaction — do not just repeat merchant_raw. Explain what the transaction "
        "likely was for and include any other relevant context from this fragment.\n"
        "If bank_name or account_hint isn't stated in this fragment, use null — never "
        "a placeholder phrase like 'not mentioned' or 'unknown', and never add bank_name "
        "or account_hint as an extra_fields entry (they always belong in the dedicated "
        "top-level fields, never duplicated into extra_fields). Each key in extra_fields "
        "must be unique — do not repeat the same key with a different value."
    )
