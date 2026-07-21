"""LangGraph pipeline — chunked extraction with tunable per-batch concurrency.

Extracts one batch of up to `max_parallel` chunks per tick (concurrently
within a batch, sequentially across batches) so total throughput stays
tunable against a per-minute token budget: max_parallel=1 (default) is fully
sequential; raising it trades budget headroom for speed.
"""

import asyncio
import time
from typing import cast

from typing_extensions import TypedDict

from app.core.config import settings
from app.core.logging import get_logger, raw_content_fields
from app.features.ingestion.normalizer.chunking import _build_prompt, _split_into_chunks
from app.features.ingestion.normalizer.schemas import ExtractedStatement, ExtraField

logger = get_logger(__name__)


class _NormalizationState(TypedDict):
    chunks: list[list[dict]]
    index: int
    max_parallel: int
    known_categories: list[str]
    bank_name: str | None
    account_hint: str | None
    transactions: list[dict]
    extra_fields: list[dict]


def _extra_fields_to_dicts(fields: list[ExtraField]) -> list[dict]:
    return [f.model_dump() for f in fields]


async def _extract_one_chunk(
    chunk_index: int, chunk: list[dict], known_categories: list[str]
) -> ExtractedStatement:
    from app.core.llm import get_chat_model

    prompt = _build_prompt(chunk, known_categories)
    # Confirmed against a real model: occasionally emits a corrupted JSON
    # escape (e.g. an invalid \u sequence inside a transliterated name) that
    # the provider's own strict-mode validation rejects — a transient
    # generation glitch, not a schema/prompt defect; retrying the same chunk
    # succeeds. `with_retry` is the Runnable's own mechanism (Constitution
    # VIII) rather than a hand-rolled retry loop.
    structured_llm = (
        get_chat_model(max_tokens=settings.normalization_chunk_max_tokens)
        .with_structured_output(ExtractedStatement)
        .with_retry(stop_after_attempt=3)
    )
    logger.info(
        "normalize_chunk_dispatching",
        chunk_index=chunk_index,
        prompt_chars=len(prompt),
        **raw_content_fields(prompt=prompt),
    )
    start = time.monotonic()
    try:
        result = cast(ExtractedStatement, await structured_llm.ainvoke(prompt))
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


async def _extract_batch_node(state: _NormalizationState) -> dict:
    start_index = state["index"]
    batch = state["chunks"][start_index : start_index + state["max_parallel"]]
    logger.info(
        "normalize_batch_starting",
        chunk_start=start_index,
        chunk_end=start_index + len(batch) - 1,
        total_chunks=len(state["chunks"]),
        max_parallel=state["max_parallel"],
    )
    batch_start = time.monotonic()
    results = await asyncio.gather(
        *(
            _extract_one_chunk(start_index + i, chunk, state["known_categories"])
            for i, chunk in enumerate(batch)
        )
    )
    logger.info("normalize_batch_finished", duration_s=round(time.monotonic() - batch_start, 1))

    bank_name = state["bank_name"]
    account_hint = state["account_hint"]
    transactions = list(state["transactions"])
    extra_fields = list(state["extra_fields"])
    for result in results:
        bank_name = bank_name or result.bank_name
        account_hint = account_hint or result.account_hint
        transactions.extend(t.model_dump() for t in result.transactions)
        extra_fields.extend(_extra_fields_to_dicts(result.extra_fields))

    return {
        "index": start_index + len(batch),
        "bank_name": bank_name,
        "account_hint": account_hint,
        "transactions": transactions,
        "extra_fields": extra_fields,
    }


def _has_more_chunks(state: _NormalizationState) -> str:
    return "extract_batch" if state["index"] < len(state["chunks"]) else "__end__"


def _build_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(_NormalizationState)
    graph.add_node("extract_batch", _extract_batch_node)
    graph.set_entry_point("extract_batch")
    graph.add_conditional_edges(
        "extract_batch", _has_more_chunks, {"extract_batch": "extract_batch", "__end__": END}
    )
    return graph.compile()


class LangGraphNormalizerClient:
    """Real `NormalizerClient` — a LangGraph loop over prompt-sized chunks."""

    def __init__(self):
        self._graph = _build_graph()

    async def normalize(
        self, content_list: list, markdown: str, known_categories: list[str]
    ) -> tuple[dict, str]:
        chunks = _split_into_chunks(content_list, markdown)
        if not chunks:
            return {
                "bank_name": None,
                "account_hint": None,
                "transactions": [],
            }, settings.model_name

        logger.info(
            "normalize_starting",
            chunk_count=len(chunks),
            max_parallel=max(1, settings.normalization_max_parallel_chunks),
        )
        overall_start = time.monotonic()
        final_state = await self._graph.ainvoke(
            {
                "chunks": chunks,
                "index": 0,
                "max_parallel": max(1, settings.normalization_max_parallel_chunks),
                "known_categories": known_categories,
                "bank_name": None,
                "account_hint": None,
                "transactions": [],
                "extra_fields": [],
            }
        )
        logger.info(
            "normalize_finished",
            duration_s=round(time.monotonic() - overall_start, 1),
            transaction_count=len(final_state["transactions"]),
        )

        normalized = {
            "bank_name": final_state["bank_name"],
            "account_hint": final_state["account_hint"],
            "transactions": final_state["transactions"],
        }
        if final_state["extra_fields"]:
            normalized["extra_fields"] = final_state["extra_fields"]
        return normalized, settings.model_name
