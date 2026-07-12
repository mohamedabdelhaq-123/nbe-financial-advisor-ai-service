"""MinerU document-parsing client.

Consumers depend only on the `MineruClient` protocol, obtained via
`get_mineru_client()` — never on `HttpMineruClient` directly. This keeps a
future mock implementation (see specs/004-document-processor/research.md §8,
deferred — not built in this feature) swappable with zero change to any
caller.
"""

import json
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Protocol

import httpx

from app.core.config import settings

_CONTENT_LIST_NAME = "content_list.json"


@dataclass
class ParsedDocument:
    markdown: str
    content_list: list
    images: dict[str, bytes] = field(default_factory=dict)


class MineruClient(Protocol):
    async def parse_document(self, file_bytes: bytes, filename: str) -> ParsedDocument: ...


def _extract_artifacts_from_zip(zip_bytes: bytes) -> ParsedDocument:
    """Unpack a MinerU ZIP response into markdown + content_list + images.

    Extracts by file basename pattern rather than an assumed fixed internal
    path, tolerating the file living at any depth. Confirmed against a real
    MinerU instance (research.md §1): files are nested under
    `{stem}/{backend_mode}/`, the markdown file is `{stem}.md`, and there are
    two content-list variants — `{stem}_content_list.json` (flat, matches the
    documented shape) and `{stem}_content_list_v2.json` (a richer, differently
    nested schema). The v2 variant is intentionally skipped in favor of the
    plain one, which matches the shape this feature's response contract
    documents.
    """
    markdown = ""
    content_list: list = []
    images: dict[str, bytes] = {}

    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            data = zf.read(name)
            base = name.rsplit("/", 1)[-1]
            if base.endswith("_content_list_v2.json"):
                continue
            if base == _CONTENT_LIST_NAME or base.endswith("_content_list.json"):
                content_list = json.loads(data.decode("utf-8")) if data else []
            elif base.endswith(".md"):
                markdown = data.decode("utf-8")
            elif base:
                images[base] = data

    return ParsedDocument(markdown=markdown, content_list=content_list, images=images)


class HttpMineruClient:
    """Real `MineruClient` — POSTs to `/file_parse` and unpacks the ZIP response."""

    async def parse_document(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
        headers = {"X-Api-Key": settings.mineru_api_key} if settings.mineru_api_key else {}
        data = {
            "response_format_zip": "true",
            "return_md": "true",
            "return_content_list": "true",
            "lang_list": ["arabic"],
        }
        files = {"files": (filename, file_bytes, "application/pdf")}

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.mineru_api_url}/file_parse",
                data=data,
                files=files,
                headers=headers,
            )
            response.raise_for_status()

        return _extract_artifacts_from_zip(response.content)


def get_mineru_client() -> MineruClient:
    """Return the configured `MineruClient`.

    Always returns `HttpMineruClient` today — `settings.use_mock_mineru` will
    select a mock implementation once one exists (deferred, research.md §8).
    """
    return HttpMineruClient()
