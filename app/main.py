from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings

app = FastAPI(title="NBE AI Service")

# Shared async OpenAI client — only used when USE_MOCK_LLM is false.
# Swap OPENAI_BASE_URL to point at vLLM with zero code changes.
_client = AsyncOpenAI(
    base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
)

# ── auth ──────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def _require_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Dependency: reject requests that don't carry the correct Bearer token."""
    if credentials is None or credentials.credentials != settings.ai_service_token:
        raise HTTPException(status_code=401, detail="Invalid or missing token")


# ── request / response schemas ────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


# ── routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    """Liveness probe — no external calls, no auth required."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    """Readiness probe — no external calls, no auth required."""
    return {"ready": True}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(_require_token)])
async def chat(body: ChatRequest) -> ChatResponse:
    """Forward a user message to the configured LLM and return its reply.

    Requires a valid Bearer token matching AI_SERVICE_TOKEN.
    When USE_MOCK_LLM=true the OpenAI client is skipped entirely and a canned
    response is returned in the exact same JSON shape — frontend and tests
    cannot tell the difference.
    """
    if settings.use_mock_llm:
        return ChatResponse(reply=f"This is a mock response to: {body.message}")

    try:
        completion = await _client.chat.completions.create(
            model=settings.model_name,
            messages=[{"role": "user", "content": body.message}],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    reply = completion.choices[0].message.content or ""
    return ChatResponse(reply=reply)
