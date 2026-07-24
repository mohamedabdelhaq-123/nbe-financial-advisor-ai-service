"""LLM-backed transaction extraction and deterministic duplicate matching.

Consumers depend only on the `NormalizerClient` protocol, obtained via
`get_normalizer_client()` — never on a strategy implementation directly,
mirroring `get_chat_model()`'s single swap point (Constitution VI/VIII).

`normalizer/` holds the strategy-agnostic contract layer: `schemas.py`
(the `NormalizerClient` Protocol + `Extracted*` structured-output models),
`mock.py` (a contract-level double), `duplicates.py` (post-extraction
enrichment), and this module's factory. Each real extraction strategy lives
in its own `agents/<name>/` subpackage holding everything specific to how
that strategy extracts data (its LangGraph graph, chunking logic, prompt
templates). Exactly one strategy exists today (`chunked_langgraph`); adding
a second means adding a sibling `agents/<name>/` subpackage, one new member
on the `normalizer_strategy` Literal, and one new branch in
`get_normalizer_client()` — never touching an existing strategy's files.

Structured output is enforced by the provider SDK's native mechanism
(`ChatOpenAI.with_structured_output`) rather than a hand-rolled JSON-rescue
parser; table-row splitting uses a real HTML parser (BeautifulSoup) rather
than hand-rolled regex over markup (Constitution VIII).
"""

from app.core.config import settings
from app.features.ingestion.normalizer.agents.chunked_langgraph.chunking import (
    _split_into_chunks,
    _split_table_entry,
)
from app.features.ingestion.normalizer.agents.chunked_langgraph.graph import (
    ChunkedLangGraphNormalizerClient,
)
from app.features.ingestion.normalizer.duplicates import find_duplicate
from app.features.ingestion.normalizer.mock import MockNormalizerClient
from app.features.ingestion.normalizer.schemas import (
    ExtractedStatement,
    ExtractedTransaction,
    ExtraField,
    NormalizerClient,
)

__all__ = [
    "ChunkedLangGraphNormalizerClient",
    "ExtraField",
    "ExtractedStatement",
    "ExtractedTransaction",
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
    """Return the configured `NormalizerClient`.

    The mock short-circuit stays first so `USE_MOCK_LLM=1` is honored
    regardless of the configured strategy. For the real path, the active
    implementation is selected by `settings.chat_model.normalizer_strategy`
    (a `Literal`, so an invalid value is rejected at config-parse time per
    Constitution VII) rather than a bare mock/real bool branch.
    """
    if settings.chat_model.use_mock:
        return MockNormalizerClient()
    if settings.chat_model.normalizer_strategy == "chunked_langgraph":
        return ChunkedLangGraphNormalizerClient()
    # Unreachable: `normalizer_strategy` is a Literal["chunked_langgraph"], so
    # any other value is a Pydantic parse-time failure, not a runtime branch.
    raise ValueError(  # pragma: no cover
        f"unknown normalizer_strategy: {settings.chat_model.normalizer_strategy!r}"
    )
