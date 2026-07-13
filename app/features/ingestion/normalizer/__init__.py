"""LLM-backed transaction extraction (LangGraph) and deterministic duplicate matching.

Consumers depend only on the `NormalizerClient` protocol, obtained via
`get_normalizer_client()` — never on `LangGraphNormalizerClient` directly,
mirroring `mineru_client.py`'s `MineruClient`/`get_mineru_client()` shape.
Structured output is enforced by the provider SDK's native mechanism
(`ChatOpenAI.with_structured_output`) rather than a hand-rolled JSON-rescue
parser; table-row splitting uses a real HTML parser (BeautifulSoup) rather
than hand-rolled regex over markup (Constitution VIII).

Split into submodules by concern: `schemas.py` (structured-output contract),
`chunking.py` (splitting OCR content into prompt-sized pieces), `graph.py`
(the LangGraph extraction pipeline + `LangGraphNormalizerClient`), `mock.py`
(`MockNormalizerClient`), and `duplicates.py` (`find_duplicate`).
"""

from app.core.config import settings
from app.features.ingestion.normalizer.chunking import _split_into_chunks, _split_table_entry
from app.features.ingestion.normalizer.duplicates import find_duplicate
from app.features.ingestion.normalizer.graph import LangGraphNormalizerClient
from app.features.ingestion.normalizer.mock import MockNormalizerClient
from app.features.ingestion.normalizer.schemas import (
    ExtractedStatement,
    ExtractedTransaction,
    ExtraField,
    NormalizerClient,
)

__all__ = [
    "ExtraField",
    "ExtractedStatement",
    "ExtractedTransaction",
    "LangGraphNormalizerClient",
    "MockNormalizerClient",
    "NormalizerClient",
    "find_duplicate",
    "get_normalizer_client",
    # Re-exported for whitebox unit tests (test_normalizer.py), not for
    # production call sites.
    "_split_into_chunks",
    "_split_table_entry",
]


def get_normalizer_client() -> NormalizerClient:
    """Return the configured `NormalizerClient` — mock or real LangGraph pipeline."""
    if settings.use_mock_llm:
        return MockNormalizerClient()
    return LangGraphNormalizerClient()
