from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

# Entry `type`s rendered as their `text` field verbatim, as a plain paragraph.
# These carry statement metadata (page footers/headers stating account/period
# info) worth keeping, not discarding as boilerplate.
_PLAIN_TEXT_TYPES = frozenset(
    {"header", "footer", "page_number", "aside_text", "page_footnote"}
)


def _join(*parts: str) -> str:
    return "\n".join(p for p in parts if p)


def _text_field(entry: dict, key: str) -> str:
    return str(entry.get(key) or "").strip()


def _heading_level(level: object) -> int:
    if isinstance(level, bool):
        return 0
    if isinstance(level, int):
        return max(0, min(level, 6))
    if isinstance(level, str) and level.strip().isdigit():
        return max(0, min(int(level.strip()), 6))
    return 0


class MarkdownRenderer:
    """Renders `content_list` entries to markdown, entry-type by entry-type."""

    def render(self, entries: list[dict]) -> str:
        """Render a list of `content_list` entries to markdown."""
        return "\n\n".join(rendered for e in entries if (rendered := self.render_entry(e)))

    def render_entry(self, entry: dict) -> str:
        """Render one `content_list` entry to markdown text ("" if it contributes nothing)."""
        entry_type = entry.get("type")
        if entry_type == "text":
            return self._render_text(entry)
        if entry_type in _PLAIN_TEXT_TYPES:
            return _text_field(entry, "text")
        if entry_type == "list":
            return self._render_list(entry)
        if entry_type == "equation":
            return _text_field(entry, "text")
        if entry_type == "image":
            return self._render_image_like(
                entry, caption_key="image_caption", footnote_key="image_footnote"
            )
        if entry_type == "chart":
            return self._render_image_like(
                entry, caption_key="chart_caption", footnote_key="chart_footnote"
            )
        if entry_type == "table":
            return self._render_table(entry)
        if entry_type == "code":
            return self._render_code(entry)
        # Defensive fallback: render a `text`-shaped field if the entry happens to
        # have one, else contribute nothing — never invent content (spec edge case).
        logger.debug("markdown_render_unknown_type", entry_type=entry_type)
        return _text_field(entry, "text")

    def _render_text(self, entry: dict) -> str:
        text = _text_field(entry, "text")
        if not text:
            return ""
        depth = _heading_level(entry.get("text_level"))
        return f"{'#' * depth} {text}" if depth else text

    def _render_list(self, entry: dict) -> str:
        lines: list[str] = []
        for item in entry.get("list_items") or []:
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                value = str(item.get("text") or item.get("content") or "").strip()
            else:
                value = str(item).strip()
            if value:
                lines.append(f"- {value}")
        return "\n".join(lines)

    def _render_image_like(self, entry: dict, *, caption_key: str, footnote_key: str) -> str:
        return _join(
            _text_field(entry, caption_key),
            _text_field(entry, footnote_key),
            _text_field(entry, "content"),
        )

    def _render_table(self, entry: dict) -> str:
        return _join(
            _text_field(entry, "table_caption"),
            str(entry.get("table_body") or "").strip(),
            _text_field(entry, "table_footnote"),
        )

    def _render_code(self, entry: dict) -> str:
        body = _text_field(entry, "code_body")
        language = _text_field(entry, "sub_type")
        fenced = f"```{language}\n{body}\n```" if body else ""
        return _join(
            _text_field(entry, "caption"),
            fenced,
            _text_field(entry, "footnote"),
        )
