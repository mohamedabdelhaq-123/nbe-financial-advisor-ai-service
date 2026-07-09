"""Bearer-token authentication for Django-facing endpoints."""

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer = HTTPBearer(auto_error=False)


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Dependency: reject requests that don't carry the correct Bearer token.

    Applied to every route beyond the liveness/readiness probes. The token is
    the shared secret between the Django backend and this internal service.
    """
    if credentials is None or credentials.credentials != settings.ai_service_token:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
