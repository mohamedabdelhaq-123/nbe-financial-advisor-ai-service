"""Unit tests for `content_list` -> markdown rendering (FR-004, T011).

One case per entry `type` from research.md §4's table, plus the unknown-type
fallback. Entries that carry no renderable text contribute nothing rather
than inventing content.
"""

from app.features.ingestion.normalizer.markdown_render import MarkdownRenderer

renderer = MarkdownRenderer()


def test_text_entry_renders_as_plain_paragraph():
    assert renderer.render_entry({"type": "text", "text": "Account: 1234"}) == "Account: 1234"


def test_text_entry_with_text_level_renders_as_markdown_heading():
    assert (
        renderer.render_entry({"type": "text", "text": "Statement", "text_level": 2})
        == "## Statement"
    )


def test_plain_text_family_types_render_text_verbatim_as_paragraph():
    for t in ("header", "footer", "page_number", "aside_text", "page_footnote"):
        assert renderer.render_entry({"type": t, "text": f"{t} note"}) == f"{t} note"


def test_list_entry_renders_list_items_as_bullet_list():
    rendered = renderer.render_entry(
        {"type": "list", "sub_type": "ref_text", "list_items": ["Item one", "Item two"]}
    )
    assert rendered == "- Item one\n- Item two"


def test_equation_entry_renders_latex_text_when_present():
    assert renderer.render_entry({"type": "equation", "text": "E = mc^2"}) == "E = mc^2"


def test_equation_entry_with_only_img_path_contributes_nothing():
    assert renderer.render_entry({"type": "equation", "img_path": "x.png"}) == ""


def test_image_entry_renders_caption_footnote_then_content_in_order():
    rendered = renderer.render_entry(
        {
            "type": "image",
            "image_caption": "Logo",
            "image_footnote": "top-right",
            "content": "NBE",
        }
    )
    assert rendered == "Logo\ntop-right\nNBE"


def test_image_entry_contributes_nothing_when_all_fields_empty():
    assert renderer.render_entry({"type": "image"}) == ""


def test_chart_entry_treated_like_image_uses_chart_caption_footnote():
    rendered = renderer.render_entry(
        {
            "type": "chart",
            "chart_caption": "Spending",
            "chart_footnote": "per month",
            "content": "",
        }
    )
    assert rendered == "Spending\nper month"


def test_table_entry_keeps_table_body_as_verbatim_html_with_caption_and_footnote():
    html = "<table><tr><td>2026-01-01</td></tr></table>"
    rendered = renderer.render_entry(
        {"type": "table", "table_caption": "Transactions", "table_body": html,
         "table_footnote": "balance brought forward"}
    )
    assert rendered == f"Transactions\n{html}\nbalance brought forward"


def test_code_entry_renders_fenced_block_tagged_with_subtype_plus_caption():
    rendered = renderer.render_entry(
        {"type": "code", "sub_type": "python", "code_body": "print(1)",
         "caption": "snippet"}
    )
    assert rendered == "snippet\n```python\nprint(1)\n```"


def test_unknown_type_falls_back_to_text_field_when_present():
    assert renderer.render_entry({"type": "something_new", "text": "kept"}) == "kept"


def test_unknown_type_with_no_text_contributes_nothing():
    assert renderer.render_entry({"type": "something_new", "img_path": "x.png"}) == ""


def test_render_joins_entries_with_blank_line_separators():
    entries = [
        {"type": "text", "text": "Intro"},
        {"type": "table", "table_body": "<table></table>"},
        {"type": "image"},  # contributes nothing -> dropped
    ]
    assert renderer.render(entries) == "Intro\n\n<table></table>"
