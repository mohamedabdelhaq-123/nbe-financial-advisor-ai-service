"""
LLM provider access.

All model access goes through this module so the backing provider stays
configurable: swap OPENAI_BASE_URL/MODEL_NAME to point at OpenAI or a
self-hosted vLLM endpoint with zero code changes. The model is never hardcoded
at a call site.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import settings

# Pass as config={"tags": [INTERNAL_CALL_TAG]} on any .ainvoke()/.astream()
# call whose result is a decision/extraction the model consumes internally,
# never the user-facing reply — e.g. Maestro's own routing classification,
# or investment_plan_node's per-turn answer extraction. LangGraph's
# stream_mode="messages" replays the raw output of *every* LLM call made
# anywhere during a graph run, not just calls whose surrounding node is
# itself streaming to the user — confirmed empirically: an internal call
# made from a node that is NOT in service.py's _LEAF_NODES (e.g. "maestro")
# is harmless purely by accident, since that node name gets filtered out
# entirely; the same call made from a leaf node (e.g. "investment_plan",
# which also has genuine user-facing output) has no such protection and its
# raw structured-output JSON would otherwise stream through as if it were
# real specialist output — both mislabeling agent_selected and leaking into
# the token stream. service.py checks for this tag before doing anything
# else with a chunk.
INTERNAL_CALL_TAG = "internal-llm-call"


@lru_cache(maxsize=None)
def get_chat_model(
    max_tokens: int | None = None,
    disable_reasoning: bool = False,
    streaming: bool = False,
    model_name: str | None = None,
) -> ChatOpenAI:
    """Return the configured chat model.

    Never called in mock mode — callers short-circuit on
    settings.chat_model.use_mock before reaching a real provider.
    `max_tokens` is an optional output-token ceiling for callers whose response
    shape needs more room than the provider's own default (e.g. a verbose
    structured-output schema repeated across several items) — confirmed
    necessary against a real provider, which otherwise cut a multi-transaction
    structured response off mid-JSON.

    `disable_reasoning` suppresses hidden reasoning tokens on a hybrid
    reasoning model. Per-caller rather than global: a caller doing extraction
    against a fixed schema gains nothing from reasoning but pays its latency,
    while an analysis or planning caller may want it kept.

    `model_name` optionally selects another model at the same configured
    provider. This lets small structured tasks use a suitable model without
    coupling them to the advisor reply model.

    `streaming` decides whether `.ainvoke()` hits the provider's streaming API.
    It is what makes token-by-token output possible *at all*: LangGraph's
    `astream(stream_mode="messages")` reads tokens off the callback stream, and
    langchain only emits those callbacks when the underlying call streams.
    With it off, `ainvoke` does one blocking request and the whole reply
    surfaces as a single chunk once generation has already finished — the
    stream is then "working" in the sense that frames flow, but there is
    exactly one of them.

    Note it must be passed explicitly to matter: langchain's `_should_stream`
    tests `"streaming" in model_fields_set`, so relying on the field's default
    is not the same as setting it.

    Defaults to False so non-conversational callers are untouched — in
    particular the ingestion normalizer, whose `with_structured_output` calls
    have no user watching them and no reason to change shape.
    """
    return ChatOpenAI(
        base_url=settings.chat_model.openai_base_url,
        model=model_name or settings.chat_model.model_name,
        api_key=settings.chat_model.openai_api_key,
        max_tokens=max_tokens,  # type: ignore[call-arg]  # real pydantic field; no mypy plugin configured to see it
        streaming=streaming,
        request_timeout=600,  # don't hang indefinitely on slow/queued free-tier LLM calls
        # None leaves the field out of the request entirely, so a provider that
        # rejects "none" (a model whose reasoning is mandatory) is unaffected
        # until a caller opts in.
        reasoning_effort="none" if disable_reasoning else None,
    )
