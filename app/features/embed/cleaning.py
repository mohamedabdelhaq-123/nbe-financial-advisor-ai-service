"""Unicode/OCR-noise cleaning for embedding input.

OCR'd Arabic statements arrive carrying bidi controls, tatweel, tashkeel and
Arabic-Indic digits, so two merchant names that render identically embed as
different vectors unless they are normalized first. Applied at the single
embedding choke point (`embed.service.embed_texts`) so stored document text and
query text always get the same transform — cleaning one side only is worse than
cleaning neither.

Deliberately stops short of alef/ya/ta-marbuta unification and casefolding:
that is lexical-search normalization, and for a dense subword model it merges
genuinely distinct words. This is normalization, not redaction — nothing here
removes PII.
"""

import re
import unicodedata

from app.core.logging import get_logger

logger = get_logger(__name__)

# Whitespace collapse handles these; every other control/format codepoint goes,
# which is what removes bidi marks, isolates, ZWJ/ZWNJ, BOM and soft hyphen.
_KEPT_CONTROLS = frozenset("\t\n\r")
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs"})

# Spelled out as codepoints because these marks are invisible in an editor.
# Narrower than category Mn on purpose — the U+06D6..U+06ED run is interrupted by
# U+06E5/U+06E6 (letters) and U+06E9 (a symbol), none of which are vowel marks.
_TASHKEEL_RANGES = (
    (0x064B, 0x065F),  # fathatan..wavy hamza below
    (0x0670, 0x0670),  # superscript alef
    (0x06D6, 0x06DC),
    (0x06DF, 0x06E4),
    (0x06E7, 0x06E8),
    (0x06EA, 0x06ED),
)
_TASHKEEL_RE = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _TASHKEEL_RANGES) + "]"
)

_WHITESPACE_RE = re.compile(r"\s+")

# Tatweel (U+0640) is a pure justification glyph with no semantic content; Arabic-Indic
# and extended Arabic-Indic digits denote the same values as their ASCII counterparts.
_TRANSLATION = str.maketrans(
    {chr(0x0640): None}
    | {chr(0x0660 + i): str(i) for i in range(10)}
    | {chr(0x06F0 + i): str(i) for i in range(10)}
)


def clean_for_embedding(text: str, *, max_chars: int | None = None) -> str:
    """Normalize a single string for embedding. Idempotent.

    `max_chars` of 0 or None disables truncation.
    """
    # NFKC first so the steps below see canonical codepoints — it folds the Arabic
    # presentation forms OCR emits back onto standard letters, and NBSP onto a space.
    normalized = unicodedata.normalize("NFKC", text)

    visible = "".join(
        ch
        for ch in normalized
        if ch in _KEPT_CONTROLS or unicodedata.category(ch) not in _DROPPED_CATEGORIES
    )
    folded = _TASHKEEL_RE.sub("", visible).translate(_TRANSLATION)
    cleaned = _WHITESPACE_RE.sub(" ", folded).strip()

    # Input that is nothing but invisibles cleans away entirely; embedding "" would
    # break the caller's positional alignment between inputs and returned vectors.
    if not cleaned:
        cleaned = text.strip()

    if max_chars and len(cleaned) > max_chars:
        logger.warning(
            "embedding_input_truncated", original_chars=len(cleaned), max_chars=max_chars
        )
        cleaned = cleaned[:max_chars]

    return cleaned


def clean_texts(texts: list[str], *, max_chars: int | None = None) -> list[str]:
    return [clean_for_embedding(t, max_chars=max_chars) for t in texts]
