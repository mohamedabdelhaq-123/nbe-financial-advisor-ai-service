"""LangGraph pipeline — Send-based fan-out extraction with max_concurrency-bounded execution.

One `ExtractChunkNode` instance processes exactly one chunk; `DispatchChunks`
emits one `Send` per chunk (LangGraph's dynamic map-fan-out pattern); `transactions`/
`extra_fields` state fields use `operator.add` reducers so concurrent branch
results merge automatically, and `bank_name`/`account_number` use a
first-non-null-wins reducer. Concurrency is bounded by passing
`config={"max_concurrency": ...}` to `ainvoke()` (research.md §6) — LangGraph's
own asyncio.Semaphore-backed executor (verified in `langgraph/pregel/_executor.py`),
not a hand-rolled batch-tick loop (Constitution VIII).

All-or-nothing failure (FR-016) needs no extra code: an unhandled exception in
any `Send`-dispatched branch propagates out of `ainvoke()` — LangGraph does not
swallow or partially-succeed a superstep by default.
"""

import operator
import time
from typing import Annotated, cast

from langchain_core.runnables import RunnableConfig
from typing_extensions import TypedDict

from app.core.config import settings
from app.core.logging import get_logger, raw_content_fields
from app.features.ingestion.normalizer.agents.chunked_langgraph import prompts
from app.features.ingestion.normalizer.agents.chunked_langgraph.chunking import (
    _split_into_chunks,
)
from app.features.ingestion.normalizer.markdown_render import MarkdownRenderer
from app.features.ingestion.normalizer.schemas import ExtractedStatement, ExtraField

logger = get_logger(__name__)


def _first_non_null(old: object, new: object) -> object:
    """Reducer for scalar `str | None` fields: keep the first non-null value.

    Concurrent branches can each set or not-set bank_name/account_number; a
    determined value from any branch wins, and None only if none set it.
    """
    return old or new


class _NormalizationState(TypedDict):
    chunks: list[list[dict]]
    known_categories: list[str]
    statement_id: str
    ocr_result_id: str
    bank_name: Annotated[str | None, _first_non_null]
    account_number: Annotated[str | None, _first_non_null]
    transactions: Annotated[list[dict], operator.add]
    extra_fields: Annotated[list[dict], operator.add]


class _ChunkInput(TypedDict):
    chunk: list[dict]
    chunk_index: int
    known_categories: list[str]
    statement_id: str
    ocr_result_id: str


def _extra_fields_to_dicts(fields: list[ExtraField]) -> list[dict]:
    return [f.model_dump() for f in fields]


class ExtractChunkNode:
    """Graph node — extracts transactions/fields from exactly one chunk."""

    def __init__(self, renderer: MarkdownRenderer | None = None) -> None:
        self._renderer = renderer or MarkdownRenderer()

    async def __call__(self, state: _ChunkInput) -> dict:
        """Process exactly one chunk; the state reducers merge concurrent results."""
        result = await self._extract_one_chunk(
            state["chunk_index"],
            state["chunk"],
            state["known_categories"],
            state["statement_id"],
            state["ocr_result_id"],
        )
        return {
            "transactions": [t.model_dump() for t in result.transactions],
            "extra_fields": _extra_fields_to_dicts(result.extra_fields),
            "bank_name": result.bank_name,
            "account_number": result.account_number,
        }

    async def _extract_one_chunk(
        self,
        chunk_index: int,
        chunk: list[dict],
        known_categories: list[str],
        statement_id: str,
        ocr_result_id: str,
    ) -> ExtractedStatement:
        from app.core.llm import get_chat_model

        prompt = prompts.get_normalization_prompt().render(
            chunk=self._renderer.render(chunk), known_categories=known_categories
        )
        # `with_retry` is the Runnable's own mechanism (Constitution VIII) rather
        # than a hand-rolled retry loop. Confirmed against a real model: a chunk
        # occasionally emits a transient glitch the provider's strict-mode
        # validation rejects; retrying the same chunk succeeds.
        structured_llm = (
            get_chat_model(
                max_tokens=settings.chat_model.normalization_chunk_max_tokens,
                disable_reasoning=False,
            )
            .bind(reasoning_effort="low")
            .with_structured_output(ExtractedStatement)
            .with_retry(stop_after_attempt=3)
        )
        # FR-012/FR-015: stamp business context onto the RunnableConfig so this
        # service's existing global auto-instrumentation groups every per-chunk LLM
        # call for one statement under one traceable unit, each individually
        # filterable by statement/chunk/prompt-version.
        #
        # TODO(Constitution Principle III exception): the same auto-instrumentation
        # path also exports the unmasked `account_number` (FR-002) carried in the
        # prompt/response content UN-REDACTED — today's RedactionSpanProcessor only
        # recognizes card/phone/email shapes, not bank account numbers. Explicitly
        # deferred out of scope for this feature (2026-07-23 clarification) and
        # tracked as a separate backlog item; see plan.md Constitution Check and
        # research.md §10. Do NOT let this gap disappear silently.
        config: RunnableConfig = {
            "metadata": {
                "statement_id": statement_id,
                "ocr_result_id": ocr_result_id,
                "chunk_index": chunk_index,
                "prompt_version": prompts.get_prompt_version(),
            },
            "tags": [f"ingestion.normalize.chunk:{chunk_index}"],
        }
        logger.info(
            "normalize_chunk_dispatching",
            chunk_index=chunk_index,
            prompt_chars=len(prompt),
            **raw_content_fields(prompt=prompt),
        )
        start = time.monotonic()
        try:
            result = cast(ExtractedStatement, await structured_llm.ainvoke(prompt, config=config))
        except Exception:
            logger.warning(
                "normalize_chunk_failed",
                chunk_index=chunk_index,
                duration_s=round(time.monotonic() - start, 1),
            )
            raise
        logger.info(
            "normalize_chunk_done",
            chunk_index=chunk_index,
            duration_s=round(time.monotonic() - start, 1),
            transaction_count=len(result.transactions),
        )
        return result


class DispatchChunks:
    """Graph edge — emits one `Send` per chunk, LangGraph's dynamic map-fan-out from START."""

    def __call__(self, state: _NormalizationState) -> list:
        from langgraph.types import Send

        return [
            Send(
                "extract_chunk",
                {
                    "chunk": chunk,
                    "chunk_index": index,
                    "known_categories": state["known_categories"],
                    "statement_id": state["statement_id"],
                    "ocr_result_id": state["ocr_result_id"],
                },
            )
            for index, chunk in enumerate(state["chunks"])
        ]


def _build_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(_NormalizationState)
    graph.add_node("extract_chunk", ExtractChunkNode())
    graph.add_conditional_edges(START, DispatchChunks(), ["extract_chunk"])
    graph.add_edge("extract_chunk", END)
    return graph.compile()


class ChunkedLangGraphNormalizerClient:
    """Real `NormalizerClient` — LangGraph Send fan-out over prompt-sized chunks."""

    def __init__(self):
        self._graph = _build_graph()

    async def normalize(
        self,
        content_list: list,
        markdown: str,
        known_categories: list[str],
        *,
        statement_id: str,
        ocr_result_id: str,
    ) -> tuple[ExtractedStatement, str]:
        chunks = _split_into_chunks(content_list, markdown)
        if not chunks:
            return ExtractedStatement(), settings.chat_model.model_name

        max_concurrency = max(1, settings.chat_model.normalization_max_parallel_chunks)
        logger.info("normalize_starting", chunk_count=len(chunks), max_concurrency=max_concurrency)
        overall_start = time.monotonic()
        final_state = await self._graph.ainvoke(
            {
                "chunks": chunks,
                "known_categories": known_categories,
                "statement_id": statement_id,
                "ocr_result_id": ocr_result_id,
                "bank_name": None,
                "account_number": None,
                "transactions": [],
                "extra_fields": [],
            },
            config={"max_concurrency": max_concurrency},
        )
        logger.info(
            "normalize_finished",
            duration_s=round(time.monotonic() - overall_start, 1),
            transaction_count=len(final_state["transactions"]),
        )

        normalized = ExtractedStatement(
            bank_name=final_state["bank_name"],
            account_number=final_state["account_number"],
            transactions=final_state["transactions"],
            extra_fields=final_state["extra_fields"],
        )
        return normalized, settings.chat_model.model_name
