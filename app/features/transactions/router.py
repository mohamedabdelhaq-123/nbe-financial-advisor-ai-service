"""Transaction embedding HTTP surface — accepts transaction IDs, persists their embeddings."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException

from app.backend_db import get_backend_session
from app.core.db import get_own_session
from app.core.security import ERROR_RESPONSES, require_token
from app.features.transactions.schemas import (
    TransactionEmbedRequest,
    TransactionEmbedResponse,
    TransactionEmbedResult,
)
from app.features.transactions.service import TransactionsNotFoundError, embed_transactions

router = APIRouter(
    prefix="/internal/transactions", tags=["transactions"], dependencies=[Depends(require_token)]
)

# embed_transactions() drives session_gen()/own_session_gen() via `async with`, i.e. it
# expects a callable returning an async context manager (matching the `own_pg` Testcontainers
# fixture's shape in tests). get_backend_session()/get_own_session() are plain async-generator
# dependency functions instead (built for FastAPI's own Depends() machinery), so calling them
# directly and entering them with `async with` raises `TypeError: 'async_generator' object does
# not support the asynchronous context manager protocol` — see app/features/analytics/router.py
# for the same adaptation. Wrapping them once here adapts them to the shape the service needs.
_backend_session_gen = asynccontextmanager(get_backend_session)
_own_session_gen = asynccontextmanager(get_own_session)


@router.post("/embed", response_model=TransactionEmbedResponse, responses={**ERROR_RESPONSES})
async def embed_transactions_endpoint(body: TransactionEmbedRequest):
    """Embed the given transactions and persist each vector to `transactions.embedding`.

    All-or-nothing: if any transaction ID doesn't exist, or the embedding provider
    fails partway through, nothing is written for the whole request (FR-006, FR-010).
    """
    try:
        embedded_ids = await embed_transactions(
            session_gen=_backend_session_gen,
            own_session_gen=_own_session_gen,
            transaction_ids=body.transaction_ids,
        )
    except TransactionsNotFoundError as exc:
        raise HTTPException(
            404,
            detail={
                "message": "One or more transaction IDs were not found",
                "invalid_transaction_ids": [str(tid) for tid in exc.invalid_transaction_ids],
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(502, detail="Embedding provider unavailable") from exc

    return TransactionEmbedResponse(
        results=[TransactionEmbedResult(transaction_id=tid) for tid in embedded_ids]
    )
