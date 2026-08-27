import secrets

from fastapi import FastAPI, Header, HTTPException, status

from app.market_data_gateway.config import MarketGatewaySettings
from app.market_data_gateway.schemas import QuoteRequest, QuoteResponse
from app.market_data_gateway.service import LiveEgyptMarketDataService


def create_app(settings: MarketGatewaySettings | None = None) -> FastAPI:
    resolved = settings or MarketGatewaySettings()
    service = LiveEgyptMarketDataService(resolved)
    application = FastAPI(
        title="NBE Market Data Gateway",
        version="0.1.0",
        description="Normalizes configured market sources for the AI investment planner.",
    )

    def authorize(authorization: str | None) -> None:
        expected = resolved.api_key.get_secret_value()
        if not expected:
            return
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid market gateway credential.",
            )

    @application.get("/health")
    async def health() -> dict[str, str]:
        # This is a process-health check, not a source-reachability check. The
        # gateway must be able to start unconfigured when market pricing is
        # disabled, so the rest of the Docker stack never depends on public
        # source availability.
        return {"status": "ok", "configured": str(resolved.configured).lower()}

    @application.post("/v1/quotes", response_model=QuoteResponse)
    async def quotes(
        request: QuoteRequest,
        authorization: str | None = Header(default=None),
    ) -> QuoteResponse:
        authorize(authorization)
        return QuoteResponse(quotes=await service.get_quotes(request.instruments))

    return application


app = create_app()
