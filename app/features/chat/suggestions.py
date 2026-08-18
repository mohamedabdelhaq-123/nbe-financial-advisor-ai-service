"""Follow-up suggestion generation — 3 short prompts appended to each reply."""

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.features.chat.schemas.widgets import Widget

logger = get_logger(__name__)

# Used both in mock mode and as the failure fallback — same posture as
# record_audit in service.py: a broken suggestion call must never take down
# the actual chat reply.
_FALLBACK_SUGGESTIONS = [
    "Show my spending breakdown",
    "What are my recent transactions?",
    "Help me plan my savings",
]


class SuggestedFollowUps(BaseModel):
    """Exactly 3 short follow-up prompts the user might naturally send next."""

    suggestions: list[str] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Three short, natural follow-up questions or requests the user might send "
            "next, each under ~60 characters, grounded in the reply just given."
        ),
    )


async def generate_suggestions(content: str, widget: Widget | None) -> list[str]:
    """Returns up to 3 follow-up suggestion chips for the reply just generated.

    Best-effort: any LLM or parsing failure falls back to a small static list
    rather than propagating and failing the whole chat turn.
    """
    if not content or settings.chat_model.use_mock:
        return list(_FALLBACK_SUGGESTIONS)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.core.llm import get_chat_model
        from app.features.chat.prompts import (
            get_suggestions_human_prompt,
            get_suggestions_system_prompt,
        )

        system_prompt = get_suggestions_system_prompt().render()
        human_prompt = get_suggestions_human_prompt().render(
            content=content, widget_type=widget.type if widget else None
        )
        # disable_reasoning: this is a small, fixed-shape classification-like
        # call, not a task that benefits from hidden reasoning tokens (same
        # rationale as the ingestion normalizer's structured-output calls).
        structured_llm = get_chat_model(disable_reasoning=True).with_structured_output(
            SuggestedFollowUps
        )
        result: SuggestedFollowUps = await structured_llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
        )
        cleaned = [s.strip() for s in result.suggestions if s.strip()]
        return cleaned[:3] if len(cleaned) >= 3 else list(_FALLBACK_SUGGESTIONS)
    except Exception:
        logger.exception("suggestion_generation_failed")
        return list(_FALLBACK_SUGGESTIONS)
