"""Zero-shot scope guardrail — checks whether a chat message is actually
about personal finance before it reaches any LLM (see the "unintended use"
guardrail: this is an allowlist check, not a banned-topics blocklist).

Two backends for the same model (MoritzLaurer/mDeBERTa-v3-base-mnli-xnli,
multilingual — this app serves Arabic and English), switched via
ScopeGuardSettings.mode with no other code change:

- "hosted": HF Inference API. No local weights; sends raw message text to
  Hugging Face. Good for dev/testing.
- "local": runs in-process (needs `uv sync --group local-scope-guard`).
  Self-hosted — message text never leaves this service. The intended
  production mode.

Deliberately a separate model from the chat LLM, not another prompt to it:
an NLI-family classifier has no instruction-following behavior to talk it
out of its answer the way a "classify this" prompt to the chat model can be
argued with — see the design discussion this module came out of.
"""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Deliberately short single words, not descriptive phrases — validated
# against the live endpoint. Longer, comma-joined labels like "personal
# finance, banking, or budgeting" vs "unrelated to personal finance" were
# tried first and classified almost everything as in-scope: NLI-based
# zero-shot classification templates each label into a hypothesis
# sentence, and multi-clause labels produce awkward, harder-to-entail
# hypotheses — short labels measurably discriminate better with this
# model. A fourth label ("capability", for "what can you do?"-style
# questions) was also tried and made things worse: every extra candidate
# label dilutes the score distribution across all of them, so confidence
# on cases that already worked collapsed — see _CAPABILITY_PHRASES below
# for how that case is actually handled instead. Kept small also for
# cost: every extra candidate label is another forward pass per check.
IN_SCOPE_LABEL = "finance"
GREETING_LABEL = "greeting"
OUT_OF_SCOPE_LABEL = "other"
CANDIDATE_LABELS = [IN_SCOPE_LABEL, GREETING_LABEL, OUT_OF_SCOPE_LABEL]

# Common ways users ask what this assistant can do. The classifier
# specifically struggles with these: they carry no finance vocabulary at
# all, so a bare-text model has no signal to work with — confidently
# misclassified as "other" even after label tuning (see module history).
# Matched directly instead, the same way maestro.py's classify_intent()
# keyword-matches known cases rather than trusting a classifier alone —
# and skips the classifier call entirely for a match, so these also cost
# nothing. Deliberately narrow: a small, closed, well-known set of
# phrasings, unlike CANDIDATE_LABELS above, which exists precisely
# because "is this about finance" is too open-ended to enumerate this way.
_CAPABILITY_PHRASES = (
    "what can you help me with",
    "what can you do",
    "who are you",
    "what are you",
    "ماذا يمكنك أن تفعل",
    "ما الذي يمكنك مساعدتي به",
    "من أنت",
)


def _is_known_in_scope_phrase(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _CAPABILITY_PHRASES)


@dataclass
class ScopeResult:
    in_scope: bool
    top_label: str
    score: float


def _result_from_scores(top_label: str, top_score: float) -> ScopeResult:
    """The actual pass/fail decision, shared by both backends and tested on
    its own — a classifier client is just a way of getting (label, score)
    here. Fails open on low confidence: only a *confident* out-of-scope
    call blocks the message, so an uncertain classifier doesn't refuse a
    legitimate question it's merely unsure how to label."""
    blocked = top_label == OUT_OF_SCOPE_LABEL and top_score >= settings.scope_guard.threshold
    return ScopeResult(in_scope=not blocked, top_label=top_label, score=top_score)


class ScopeClassifier(Protocol):
    async def classify(self, text: str) -> ScopeResult: ...


class HostedScopeClassifier:
    """Calls the HF Inference API. Constructed once (see get_scope_classifier)
    and reused — one client, not one per request."""

    def __init__(self) -> None:
        import httpx

        cfg = settings.scope_guard
        base_url = cfg.hosted_api_url or (
            f"https://router.huggingface.co/hf-inference/models/{cfg.model_name}"
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {cfg.hosted_api_key.get_secret_value()}"},
            timeout=10.0,
        )

    async def classify(self, text: str) -> ScopeResult:
        response = await self._client.post(
            "", json={"inputs": text, "parameters": {"candidate_labels": CANDIDATE_LABELS}}
        )
        response.raise_for_status()
        # [{"label": ..., "score": ...}, ...], sorted highest score first —
        # NOT the old api-inference.huggingface.co {"labels": [...], "scores": [...]}
        # shape; verified against the real endpoint, see PR discussion.
        data = response.json()
        top = data[0]
        return _result_from_scores(top["label"], top["score"])


class LocalScopeClassifier:
    """Runs the model in-process via `transformers`. The import is deferred
    to __init__ (not module level) specifically so that importing this
    module — or running in "hosted" mode — never requires torch/transformers
    to be installed at all; see the `local-scope-guard` uv dependency group.
    """

    def __init__(self) -> None:
        from transformers import pipeline

        self._pipeline = pipeline("zero-shot-classification", model=settings.scope_guard.model_name)

    def _classify_sync(self, text: str) -> ScopeResult:
        result = self._pipeline(text, CANDIDATE_LABELS)
        return _result_from_scores(result["labels"][0], result["scores"][0])

    async def classify(self, text: str) -> ScopeResult:
        # The pipeline call is synchronous and CPU-bound — off the event
        # loop, so one classification doesn't stall every other concurrent
        # request this process is serving.
        return await asyncio.to_thread(self._classify_sync, text)


_classifier: ScopeClassifier | None = None


def get_scope_classifier() -> ScopeClassifier:
    """Built once, on first use, and reused for the life of the process —
    same lifecycle as app.core.llm.get_chat_model()."""
    global _classifier
    if _classifier is None:
        if settings.scope_guard.mode == "local":
            _classifier = LocalScopeClassifier()
        else:
            _classifier = HostedScopeClassifier()
    return _classifier


CONTEXT_SNIPPET_CHARS = 150

# Only a reply from one of the real finance task agents counts as evidence
# the conversation is still on-topic. "general"/"refused" replies are
# deliberately excluded even though they're often finance-flavored — a
# refusal or redirect ("...I can help with budgeting, saving...") talks
# about finance to steer the user back on topic, which makes it look
# finance-relevant to the classifier without actually being genuine
# engagement. Trusting it as context let unrelated follow-up messages
# (e.g. right after a refusal) slip past the guard on borrowed vocabulary.
_TASK_INTENTS = frozenset(
    {"analysis", "planning", "investment_planning", "recommendation"}
)


def build_scope_check_text(messages: list, last_intent: str | None = None) -> str:
    """Classifier input: a short, capped snippet of the immediately
    preceding message (context for elliptical follow-ups like "what about
    this month?"), followed by the full current message, last and
    untruncated — so a genuine topic switch still dominates the premise
    instead of being rescued by stale context. Plain prose, no role labels
    or newlines: this NLI model expects natural text, not dialogue-formatted
    transcripts (unlike an LLM prompt, which handles that fine).

    `last_intent` is the intent Maestro assigned on the PREVIOUS turn
    (`state["intent"]`, still holding its old value here since this node
    runs before Maestro overwrites it for the current turn). The preceding
    message is only used as context when that intent was a real task
    agent — see _TASK_INTENTS above."""
    if not messages:
        return ""
    current = messages[-1].content if hasattr(messages[-1], "content") else ""
    current = current if isinstance(current, str) else str(current)
    if len(messages) < 2 or last_intent not in _TASK_INTENTS:
        return current
    prev = messages[-2]
    prev_text = prev.content if hasattr(prev, "content") and isinstance(prev.content, str) else ""
    prev_snippet = prev_text[:CONTEXT_SNIPPET_CHARS].strip()
    return f"{prev_snippet} {current}" if prev_snippet else current


async def check_scope(text: str) -> ScopeResult:
    """Entry point. Fails open — if the guard is disabled, or the
    classifier call itself errors (network blip, rate limit, whatever),
    the message is treated as in-scope rather than the whole chat feature
    going down because a guardrail's dependency hiccuped. This is a
    deliberate availability-over-strictness choice: revisit it if the
    threat model changes."""
    if not settings.scope_guard.enabled:
        return ScopeResult(in_scope=True, top_label="(guard disabled)", score=1.0)

    if _is_known_in_scope_phrase(text):
        return ScopeResult(in_scope=True, top_label="(capability phrase)", score=1.0)

    try:
        result = await get_scope_classifier().classify(text)
    except Exception:
        logger.exception("scope_guard_check_failed")
        return ScopeResult(in_scope=True, top_label="(check failed)", score=0.0)

    if not result.in_scope:
        # Score/label only — never the message text itself, which is the
        # exact user-supplied content this guard exists to keep out of
        # places it doesn't need to be (see strip_pii's rationale).
        logger.warning("scope_guard_blocked", top_label=result.top_label, score=result.score)
    return result
