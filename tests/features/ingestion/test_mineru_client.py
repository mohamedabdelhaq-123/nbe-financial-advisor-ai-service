"""Tests for the pure ZIP-extraction helper — no HTTP call involved."""

import io
import json
import zipfile

from app.features.ingestion.mineru_client import _extract_artifacts_from_zip


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
