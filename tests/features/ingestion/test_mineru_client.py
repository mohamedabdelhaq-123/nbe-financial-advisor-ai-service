"""Tests for the pure ZIP-extraction helper — no HTTP call involved."""

import io
import json
import zipfile

import pytest

from app.features.ingestion.mineru_client import (
    HttpMineruClient,
    MockMineruClient,
    _extract_artifacts_from_zip,
    get_mineru_client,
)
from app.features.ingestion.normalizer.chunking import _split_into_chunks


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extracts_markdown_and_content_list_by_extension():
    zip_bytes = _make_zip(
        {
            "statement.md": b"# Statement\n\n| Date | Amount |\n|---|---|\n| 2026-01-01 | 100 |",
            "content_list.json": json.dumps([{"type": "table", "content": "row"}]).encode(),
        }
    )

    parsed = _extract_artifacts_from_zip(zip_bytes)

    assert "# Statement" in parsed.markdown
    assert parsed.content_list == [{"type": "table", "content": "row"}]
    assert parsed.images == {}


def test_extracts_images_into_name_to_bytes_mapping():
    zip_bytes = _make_zip(
        {
            "statement.md": b"# Statement",
            "content_list.json": b"[]",
            "images/fig1.jpg": b"\xff\xd8\xff\xe0fake-jpeg-bytes",
            "images/fig2.png": b"\x89PNGfake-png-bytes",
        }
    )

    parsed = _extract_artifacts_from_zip(zip_bytes)

    assert parsed.images == {
        "fig1.jpg": b"\xff\xd8\xff\xe0fake-jpeg-bytes",
        "fig2.png": b"\x89PNGfake-png-bytes",
    }


def test_handles_empty_markdown_and_content_list():
    zip_bytes = _make_zip({"statement.md": b"", "content_list.json": b"[]"})

    parsed = _extract_artifacts_from_zip(zip_bytes)

    assert parsed.markdown == ""
    assert parsed.content_list == []
    assert parsed.images == {}


def test_matches_real_mineru_layout_and_skips_v2_content_list():
    """Regression test for the real ZIP layout confirmed against a live MinerU
    instance (research.md §1): files nested under `{stem}/{backend_mode}/`,
    content list named `{stem}_content_list.json` (not the bare
    `content_list.json` assumed in earlier drafts), plus a `_content_list_v2.json`
    variant that must be skipped, not treated as an image.
    """
    zip_bytes = _make_zip(
        {
            "statement/hybrid_auto/statement.md": b"## Statement",
            "statement/hybrid_auto/statement_content_list.json": json.dumps(
                [{"type": "text", "text": "Statement", "page_idx": 0}]
            ).encode(),
            "statement/hybrid_auto/statement_content_list_v2.json": json.dumps(
                [[{"type": "title", "content": {"title_content": []}}]]
            ).encode(),
        }
    )

    parsed = _extract_artifacts_from_zip(zip_bytes)

    assert parsed.markdown == "## Statement"
    assert parsed.content_list == [{"type": "text", "text": "Statement", "page_idx": 0}]
    assert parsed.images == {}


def test_get_mineru_client_returns_mock_when_use_mock_mineru(monkeypatch):
    # Patched on the mineru_client module's own `settings` reference, not
    # `app.core.config.settings` — mirrors the rationale documented at
    # tests/features/ingestion/test_normalizer.py:357-361: a reload elsewhere
    # in the suite rebinds `app.core.config.settings` to a new object that
    # this module (imported before the reload) no longer shares.
    import app.features.ingestion.mineru_client as mineru_client_module

    monkeypatch.setattr(mineru_client_module.settings, "use_mock_mineru", True)
    assert isinstance(get_mineru_client(), MockMineruClient)


def test_get_mineru_client_returns_http_when_not_mock(monkeypatch):
    import app.features.ingestion.mineru_client as mineru_client_module

    monkeypatch.setattr(mineru_client_module.settings, "use_mock_mineru", False)
    assert isinstance(get_mineru_client(), HttpMineruClient)


@pytest.mark.asyncio
async def test_mock_mineru_client_returns_fixed_deterministic_content():
    first = await MockMineruClient().parse_document(b"one-file", "a.pdf")
    second = await MockMineruClient().parse_document(b"a-completely-different-file", "b.pdf")

    assert first == second
    assert first.markdown.strip()
    assert len(first.content_list) == 2
    types = {entry["type"] for entry in first.content_list}
    assert types == {"text", "table"}
    table_entry = next(entry for entry in first.content_list if entry["type"] == "table")
    assert "rows" not in table_entry
    assert table_entry["table_body"]
    assert first.images == {}


@pytest.mark.asyncio
async def test_mock_mineru_client_table_body_is_parseable_by_real_chunking():
    parsed = await MockMineruClient().parse_document(b"file-bytes", "statement.pdf")

    chunks = _split_into_chunks(parsed.content_list, parsed.markdown)

    assert chunks
    assert all(chunk for chunk in chunks)
