"""Resource abuse / cost-based denial of service — SEC-010 in
SECURITY_AUDIT_REPORT.md.

Deterministic, offline, schema-level checks only — no load generation
against any real service, per the "never perform destructive/DoS-shaped
testing" rule. What's actually tested is whether the input schema *could*
bound a request's size before it ever reaches an expensive LLM/embedding
call, not runtime behavior under load.
"""

import pytest
from pydantic import ValidationError


@pytest.mark.redteam(id="RT-024", category="resource_abuse", severity="medium")
def test_chat_message_has_no_size_cap():
    """RT-024 — `ChatTurnRequest.message` (app/features/chat/schemas/
    request.py) used to have no `max_length`. Fixed: capped at 8000 chars.

    Preconditions: none.
    Attack input: `ChatTurnRequest(message="a" * 2_000_000, ...)` — a 2MB
    chat message.
    Expected secure behavior: rejected at the request-validation layer
    before it can reach an LLM call.
    """
    from app.features.chat.schemas import ChatTurnRequest

    huge_message = "a" * 2_000_000  # 2MB of text in one chat turn
    try:
        accepted = ChatTurnRequest(
            conversation_id="c-size-test",
            user_id="00000000-0000-4000-8000-0000000000aa",
            message=huge_message,
        )
    except ValidationError:
        return  # secure behavior confirmed
    raise AssertionError(
        f"a {len(huge_message):,}-char message was accepted with no validation error "
        f"(message field length on the accepted object: {len(accepted.message):,} chars)"
    )


@pytest.mark.redteam(id="RT-025", category="resource_abuse", severity="medium")
def test_embeddings_request_has_no_batch_size_cap():
    """RT-025 — `EmbeddingRequest.input` (app/features/embed/schemas.py)
    used to have no upper bound on the number of texts in one batch, unlike
    `TransactionEmbedRequest.transaction_ids`, which caps at 500 (see
    RT-010's positive control). Fixed: `input` now caps at
    `MAX_EMBEDDING_BATCH_SIZE` (500), mirroring that pattern.

    Preconditions: none.
    Attack input: `EmbeddingRequest(input=["some text to embed"] * 100_000)`.
    Expected secure behavior: rejected before reaching the embedding
    provider.
    """
    from app.features.embed.schemas import EmbeddingRequest

    huge_batch = ["some text to embed"] * 100_000
    try:
        accepted = EmbeddingRequest(input=huge_batch)
    except ValidationError:
        return  # secure behavior confirmed
    raise AssertionError(
        f"a batch of {len(huge_batch):,} texts was accepted with no validation error "
        f"(accepted input length: {len(accepted.input):,})"
    )
